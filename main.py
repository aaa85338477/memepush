import os
import requests
import cloudscraper
from datetime import datetime
import time
import json
import xml.etree.ElementTree as ET
import re
import html
from concurrent.futures import ThreadPoolExecutor # 🚀 新增：多线程并发库

# ==========================================
# 1. 核心配置区
# ==========================================
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL")
AI_API_KEY = os.environ.get("AI_API_KEY") 
AI_API_URL = "https://api.bltcy.ai/v1/chat/completions"
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")  

# ==========================================
# 2. 数据获取层 
# ==========================================
def fetch_twitter_trends(limit):
    if not RAPIDAPI_KEY:
        print("❌ 未配置 RAPIDAPI_KEY，跳过 Twitter 抓取")
        return []
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
    if not RAPIDAPI_KEY:
        print("❌ 未配置 RAPIDAPI_KEY，跳过 YouTube 抓取")
        return []
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
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 RSSReader/7.0'}
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
                post_body = re.sub(r'\s+', ' ', clean_text).strip()[:500] 
            result_list.append({'title': title, 'url': img_url, 'permalink': link, 'body': post_body, 'score': '🔥 榜单前列'})
        return result_list
    except Exception as e:
        print(f"抓取 Reddit r/{subreddit} 失败: {e}")
        return []

def fetch_kym_news(limit):
    url = "https://knowyourmeme.com/news.rss"
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
                img_match = re.search(r'src="(https://i\.kym-cdn\.com/[^"]+)"', description)
                if img_match: img_url = img_match.group(1)
                clean_text = re.sub(r'<[^>]+>', ' ', html.unescape(description))
                post_body = re.sub(r'\s+', ' ', clean_text).strip()[:500]
            result_list.append({'title': title, 'url': img_url, 'permalink': link, 'body': post_body, 'score': '📰 最新趋势'})
        return result_list
    except Exception as e:
        print(f"抓取 Know Your Meme 失败: {e}")
        return []

# ==========================================
# 3. AI 业务处理层 (定制化项目 Prompt + 噪音过滤)
# ==========================================
def analyze_post_with_ai(title, source_name, body, img_url):
    """调用大模型，定向产出中世纪鼠疫SLG创意，并拥有跳过权限"""
    if not AI_API_KEY:
         return "解析: 未配置 AI 密钥\n创意: 无法生成"

    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {AI_API_KEY}', 'Content-Type': 'application/json'}

    # 🚀 方案一：硬核项目背景植入
    system_prompt = """你是一位拥有五年经验的资深出海游戏买量与试玩广告（Playable Ad）策划。
    你目前正在主导一款核心手游产品：【中世纪鼠疫（黑死病）背景，前期为模拟经营（建造避难所、收容难民、分配草药/食物），后期转为SLG（暴兵、大地图战略、结盟、资源掠夺）的混合型游戏】。
    你的任务是无情过滤全网热点，并将其转化为该游戏的极致转化买量创意。"""
    
    # 🚀 方案二：脏数据过滤与指令限制
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

    try:
        response = requests.post(AI_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        return "解析: AI 解析超时\n创意: 请结合原文直达链接自行查看"

# 🚀 方案四：多线程并发处理引擎
def batch_analyze_posts(posts, source_name):
    """使用线程池并发处理数据源，大幅提升速度并剔除垃圾数据"""
    if not posts: return []
    print(f"  -> ⚡ 启动并发解析 {source_name} 的 {len(posts)} 条数据...")
    
    valid_posts = []
    # 设置最大线程数，避免触发 API 频控
    with ThreadPoolExecutor(max_workers=5) as executor:
        # map 函数能保证结果顺序与传入的帖子顺序完全一致 (保留 Top 榜单价值)
        results = executor.map(lambda p: analyze_post_with_ai(p['title'], source_name, p['body'], p['url']), posts)
        
        for post, ai_result in zip(posts, results):
            if ai_result == '跳过':
                print(f"     [过滤拦截] 判定为非游戏/敏感内容，已自动丢弃: {post['title'][:20]}...")
                continue
            
            post['ai_analysis'] = ai_result
            valid_posts.append(post)
            
    return valid_posts

# ==========================================
# 4. 消息推送层 
# ==========================================
def send_to_feishu(report_title, content_blocks):
    if not FEISHU_WEBHOOK_URL: return
    feishu_post_content = []
    section_config = {
        'twitter': "🐦 【 Twitter | 实时话题榜 】\n",
        'youtube': "▶️ 【 YouTube | 热门视频趋势 】\n",
        'kym': "🌐 【 Know Your Meme | 全网流行趋势 】\n",
        'reddit': "👾 【 Reddit | 垂直圈层热点 】\n"
    }

    for section_type, section_title in section_config.items():
        blocks_of_type = [b for b in content_blocks if b['type'] == section_type]
        if not blocks_of_type: continue
            
        feishu_post_content.append([{"tag": "text", "text": section_title}])
        for block in blocks_of_type:
            if section_type == 'reddit': feishu_post_content.append([{"tag": "text", "text": f"◼ {block['source']}"}])
            if not block['posts']:
                feishu_post_content.append([{"tag": "text", "text": "   (内容已被 AI 过滤或暂无抓取到有效数据)\n\n"}])
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
    target_subreddits = [
        'memes', 'oddlysatisfying', 'shittymobilegameads', 'AmItheAsshole',
        'TikTokCringe', 'tiktokgossip', 'holdmybeer', 'mildlyinteresting',
    ]

    today_weekday = datetime.today().weekday()
    if today_weekday == 0:
        report_title = "🏰 [周一盘点] 鼠疫SLG：全球爆款素材提取报告"
        time_filter, fetch_limit = 'week', 10
    else:
        report_title = "🛡️ [日常速递] 鼠疫SLG：全球爆款素材提取报告"
        time_filter, fetch_limit = 'day', 3

    print(f"🎯 正在生成: {report_title}...\n")
    all_content_blocks = []

    # Twitter
    twitter_posts = fetch_twitter_trends(fetch_limit)
    if twitter_posts:
        valid_posts = batch_analyze_posts(twitter_posts, "Twitter US")
        if valid_posts: all_content_blocks.append({'type': 'twitter', 'source': 'Twitter US', 'posts': valid_posts})

    # YouTube
    youtube_posts = fetch_youtube_trends(fetch_limit)
    if youtube_posts:
        valid_posts = batch_analyze_posts(youtube_posts, "YouTube US")
        if valid_posts: all_content_blocks.append({'type': 'youtube', 'source': 'YouTube US', 'posts': valid_posts})

    # KYM
    kym_posts = fetch_kym_news(fetch_limit)
    if kym_posts:
        valid_posts = batch_analyze_posts(kym_posts, "Know Your Meme")
        if valid_posts: all_content_blocks.append({'type': 'kym', 'source': 'Know Your Meme', 'posts': valid_posts})

    # Reddit
    for sub in target_subreddits:
        posts = fetch_reddit_posts(sub, time_filter, fetch_limit)
        if posts:
            valid_posts = batch_analyze_posts(posts, f"r/{sub}")
            if valid_posts: all_content_blocks.append({'type': 'reddit', 'source': f"r/{sub}", 'posts': valid_posts})
        
    print("\n📦 全网并发处理与过滤完毕，正在推送到飞书...")
    send_to_feishu(report_title, all_content_blocks)

if __name__ == "__main__":
    main()