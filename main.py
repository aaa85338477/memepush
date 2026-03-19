import os
import requests
import cloudscraper
from datetime import datetime
import time
import json
import xml.etree.ElementTree as ET
import re
import html

# ==========================================
# 1. 核心配置区
# ==========================================
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL")
AI_API_KEY = os.environ.get("AI_API_KEY") 
AI_API_URL = "https://api.bltcy.ai/v1/chat/completions"
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")  

# ==========================================
# 2. 数据获取层 (万能 RSS 引擎 + API)
# ==========================================
def fetch_twitter_trends(limit):
    if not RAPIDAPI_KEY: return []
    url = "https://twitter241.p.rapidapi.com/trends-by-location"
    querystring = {"woeid": "2424766"} 
    headers = {"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": "twitter241.p.rapidapi.com"}
    try:
        response = requests.get(url, headers=headers, params=querystring)
        response.raise_for_status()
        data = response.json()
        trends = []
        if isinstance(data, dict) and "result" in data:
            res_list = data["result"]
            if isinstance(res_list, list) and len(res_list) > 0 and "trends" in res_list[0]:
                trends = res_list[0]["trends"]
        result_list = []
        for item in trends[:limit]:
            name = item.get("name", "未知趋势")
            volume = item.get("tweet_volume")
            score = f"🔥 {volume} Tweets" if volume else "🔥 热度飙升"
            link = item.get("url") or f"https://twitter.com/search?q={name.replace('#', '%23')}"
            result_list.append({'title': name, 'url': '', 'permalink': link, 'body': "当前 Twitter 实时热门趋势话题", 'score': score})
        return result_list
    except Exception as e:
        print(f"抓取 Twitter 失败: {e}")
        return []

def fetch_youtube_trends(limit):
    if not RAPIDAPI_KEY: return []
    url = "https://youtube138.p.rapidapi.com/v2/trending"
    headers = {"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": "youtube138.p.rapidapi.com"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        videos = data.get("list", []) if isinstance(data, dict) else []
        result_list = []
        for item in videos[:limit]:
            title = item.get("title", "未知标题")
            video_id = item.get("videoId", "")
            views = item.get("viewCount") or item.get("views") or "高热度视频"
            link = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
            thumbnails = item.get("videoThumbnails", [])
            img_url = thumbnails[0].get("url") if thumbnails else ""
            result_list.append({'title': title, 'url': img_url, 'permalink': link, 'body': f"当前 YouTube 热门趋势视频，热度：{views}", 'score': f"▶️ {views}"})
        return result_list
    except Exception as e:
        print(f"抓取 YouTube 失败: {e}")
        return []

def fetch_reddit_posts(subreddit, time_filter, limit):
    url = f"https://www.reddit.com/r/{subreddit}/top.rss?t={time_filter}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 RSSReader/9.0'}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        entries = root.findall('atom:entry', ns)
        result_list = []
        for entry in entries[:limit]: 
            title = entry.find('atom:title', ns).text
            link = entry.find('atom:link', ns).attrib['href']
            content = entry.find('atom:content', ns)
            img_url, post_body = "", ""
            if content is not None and content.text:
                img_match = re.search(r'href="(https://i\.redd\.it/[^"]+)"', content.text)
                if img_match: img_url = img_match.group(1)
                clean_text = re.sub(r'<[^>]+>', ' ', html.unescape(content.text))
                # 严格限制字数，保护 AI 接口 Token 额度
                post_body = re.sub(r'\s+', ' ', clean_text).strip()[:400] 
            result_list.append({'title': title, 'url': img_url, 'permalink': link, 'body': post_body, 'score': '🔥 Reddit榜单前列'})
        return result_list
    except Exception as e:
        print(f"抓取 Reddit r/{subreddit} 失败: {e}")
        return []

def fetch_generic_rss(url, source_name, limit):
    """万能 RSS 解析器，通杀 KYM、BoredPanda 等标准 RSS 源"""
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    try:
        response = scraper.get(url)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items = root.findall('.//item')
        
        result_list = []
        for item in items[:limit]:
            title = item.find('title').text if item.find('title') is not None else "无标题"
            link = item.find('link').text if item.find('link') is not None else ""
            description = item.find('description').text if item.find('description') is not None else ""
            
            img_url, post_body = "", ""
            if description:
                # 尝试提取正文中的图片
                img_match = re.search(r'src="([^"]+)"', description)
                if img_match: img_url = img_match.group(1)
                
                clean_text = re.sub(r'<[^>]+>', ' ', html.unescape(description))
                # 严格限制字数，保护 AI 接口 Token 额度
                post_body = re.sub(r'\s+', ' ', clean_text).strip()[:400] 
                
            result_list.append({
                'title': title,
                'url': img_url,
                'permalink': link,
                'body': post_body,
                'score': f'📰 {source_name} 最新发布'
            })
        return result_list
    except Exception as e:
        print(f"抓取 {source_name} RSS 失败: {e}")
        return []

# ==========================================
# 3. AI 业务处理层 (稳定防限流)
# ==========================================
def analyze_post_with_ai(title, source_name, body, img_url):
    if not AI_API_KEY:
         return "解析: 未配置 AI 密钥\n创意: 无法生成"

    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {AI_API_KEY}', 'Content-Type': 'application/json'}

    system_prompt = """你是一位拥有五年经验的资深出海游戏买量与试玩广告（Playable Ad）策划。
    你目前正在主导一款核心手游产品：【中世纪鼠疫（黑死病）背景，前期为模拟经营（建造避难所、收容难民、分配草药/食物），后期转为SLG（暴兵、大地图战略、结盟、资源掠夺）的混合型游戏】。
    你的任务是无情过滤全网热点，并将其转化为该游戏的极致转化买量创意。"""
    
    text_prompt = f"""
    信息来源: {source_name}
    标题/话题: {title}
    背景信息: {body if body else '无附加信息'}
    
    【过滤指令（最高优先级）】：
    如果该话题属于：严肃政治选举、传统体育竞技（如NFL/NBA）、重大现实悲剧灾难等【极难且不适合转化为游戏买量广告的非娱乐向内容】。
    请直接、仅输出两个字：跳过
    绝不要包含任何其他标点或解释。

    【创意生成】：
    如果判定为可用娱乐热点/梗，请结合上述信息，严格按照以下两行格式输出（总字数控制在120字以内，绝不要使用Emoji）：
    解析: (一句话提炼该趋势的核心反差感、笑点或情绪痛点)
    创意: (一句话说明如何将其包装为我们【中世纪鼠疫/前期模拟经营/后期SLG】游戏的试玩前3秒画面、猎奇互动或抓马剧情选项)
    """

    user_content = [{"type": "text", "text": text_prompt}]
    if img_url: user_content.append({"type": "image_url", "image_url": {"url": img_url}})

    payload = {
        "model": "gemini-3.1-flash-lite-preview", 
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
        "temperature": 0.7,
        "max_tokens": 150
    }

    # API 请求保持单线程串行，增加 3 次容错重试
    for attempt in range(3):
        try:
            response = requests.post(AI_API_URL, headers=headers, json=payload, timeout=20)
            response.raise_for_status() 
            return response.json()['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"     [AI 警告] 解析《{title[:10]}...》失败 (尝试 {attempt+1}/3): {e}")
            time.sleep(3) # 失败休眠3秒后重试
            
    return "解析: AI 接口繁忙或达到限制，解析失败\n创意: 请结合原文直达链接自行查看"

def batch_analyze_posts(posts, source_name):
    if not posts: return []
    print(f"  -> ⚡ 启动顺序解析 {source_name} 的 {len(posts)} 条数据 (已开启 API 保护)...")
    
    valid_posts = []
    
    for post in posts:
        ai_result = analyze_post_with_ai(post['title'], source_name, post['body'], post['url'])
        
        if ai_result == '跳过':
            print(f"     [过滤拦截] 敏感或非游戏内容自动丢弃: {post['title'][:20]}...")
            continue
            
        post['ai_analysis'] = ai_result
        valid_posts.append(post)
        
        # 核心防封禁锁：因为 RSS 文本极短，每条请求间歇 3 秒足以保障安全
        time.sleep(3) 
            
    return valid_posts

# ==========================================
# 4. 消息推送层 
# ==========================================
def send_to_feishu(report_title, content_blocks):
    if not FEISHU_WEBHOOK_URL: return
    feishu_post_content = []
    
    # 动态渲染区块，兼容无限拓展的 RSS 源
    for block in content_blocks:
        source_title = block['source']
        
        # 根据来源动态匹配 Emoji 图标
        icon = "👾"
        if "Twitter" in source_title: icon = "🐦"
        elif "YouTube" in source_title: icon = "▶️"
        elif "RSS" in source_title: icon = "🌐"
        
        feishu_post_content.append([{"tag": "text", "text": f"{icon} 【 {source_title} 】\n"}])
        
        if not block['posts']:
            feishu_post_content.append([{"tag": "text", "text": "   (内容已被 AI 过滤或暂无有效数据)\n\n"}])
            continue
            
        for index, post in enumerate(block['posts'], start=1):
            feishu_post_content.append([{"tag": "text", "text": f"   {index}. {post['title']}  ({post['score']})"}])
            link_line = [{"tag": "text", "text": "      ↳ 链接: "}]
            if post['url']: link_line.extend([{"tag": "a", "text": "[查看封面/视觉素材]", "href": post['url']}, {"tag": "text", "text": " | "}])
            if post['permalink']: link_line.append({"tag": "a", "text": "[原文直达]", "href": post['permalink']})
            feishu_post_content.append(link_line)
            
            for line in post['ai_analysis'].split('\n'):
                clean_line = line.strip().replace("解析：", "解析: ").replace("创意：", "创意: ")
                if clean_line: feishu_post_content.append([{"tag": "text", "text": f"      ▪ {clean_line}"}])
            feishu_post_content.append([{"tag": "text", "text": "\n"}])

    payload = {"msg_type": "post", "content": {"post": {"zh_cn": {"title": report_title, "content": feishu_post_content}}}}
    try:
        requests.post(FEISHU_WEBHOOK_URL, headers={'Content-Type': 'application/json'}, json=payload)
        print("✅ 成功推送到飞书！")
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")

# ==========================================
# 5. 主程序控制中枢
# ==========================================
def main():
    # 💎 优化后的 Reddit 矩阵 (加入 MemeEconomy 和纯净版爆笑推特)
    target_subreddits = [
        'memes', 'oddlysatisfying', 'MemeEconomy', 'NonPoliticalTwitter',
        'TikTokCringe', 'tiktokgossip', 'holdmybeer', 'mildlyinteresting',
    ]
    
    # 💎 万能 RSS 订阅源列表 (极度稳定，不会超长)
    rss_feeds = [
        {"name": "Know Your Meme", "url": "https://knowyourmeme.com/news.rss"},
        {"name": "Bored Panda", "url": "https://www.boredpanda.com/feed/"}
    ]

    today_weekday = datetime.today().weekday()
    if today_weekday == 0:
        report_title = "🏰 [周一盘点] 鼠疫SLG：全球爆款素材提取报告"
        time_filter, fetch_limit = 'week', 8
    else:
        report_title = "🛡️ [日常速递] 鼠疫SLG：全球爆款素材提取报告"
        time_filter, fetch_limit = 'day', 3

    print(f"🎯 正在生成: {report_title}...\n")
    all_content_blocks = []

    # 1. 抓取 Twitter
    twitter_posts = fetch_twitter_trends(fetch_limit)
    if twitter_posts:
        valid_posts = batch_analyze_posts(twitter_posts, "Twitter 实时热搜")
        if valid_posts: all_content_blocks.append({'source': 'Twitter 实时热搜', 'posts': valid_posts})

    # 2. 抓取 YouTube
    youtube_posts = fetch_youtube_trends(fetch_limit)
    if youtube_posts:
        valid_posts = batch_analyze_posts(youtube_posts, "YouTube 热门趋势")
        if valid_posts: all_content_blocks.append({'source': 'YouTube 热门趋势', 'posts': valid_posts})

    # 3. 抓取 万能 RSS 源矩阵
    for feed in rss_feeds:
        print(f"正在抓取 {feed['name']} RSS...")
        posts = fetch_generic_rss(feed['url'], feed['name'], fetch_limit)
        if posts:
            valid_posts = batch_analyze_posts(posts, f"{feed['name']} (RSS)")
            if valid_posts: all_content_blocks.append({'source': f"{feed['name']} (RSS)", 'posts': valid_posts})

    # 4. 抓取 Reddit
    for sub in target_subreddits:
        print(f"正在抓取 r/{sub} ...")
        posts = fetch_reddit_posts(sub, time_filter, fetch_limit)
        if posts:
            valid_posts = batch_analyze_posts(posts, f"Reddit r/{sub}")
            if valid_posts: all_content_blocks.append({'source': f"Reddit r/{sub}", 'posts': valid_posts})
        
    print("\n📦 全网顺序处理与过滤完毕，正在推送到飞书...")
    send_to_feishu(report_title, all_content_blocks)

if __name__ == "__main__":
    main()
