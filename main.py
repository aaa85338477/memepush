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
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")  # 重新请回 RapidAPI 密钥

# ==========================================
# 2. 数据获取层 (新增 Twitter & YouTube)
# ==========================================
def fetch_twitter_trends(limit):
    """通过 RapidAPI 获取 Twitter 地区热搜"""
    if not RAPIDAPI_KEY:
        print("❌ 未配置 RAPIDAPI_KEY，跳过 Twitter 抓取")
        return []

    url = "https://twitter241.p.rapidapi.com/trends-by-location"
    querystring = {"woeid": "2424766"} # US 区域
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "twitter241.p.rapidapi.com"
    }

    try:
        response = requests.get(url, headers=headers, params=querystring)
        response.raise_for_status()
        data = response.json()
        
        # 防御性解析：Twitter 返回的数据通常包裹在列表中
        trends = []
        if isinstance(data, list) and len(data) > 0 and "trends" in data[0]:
            trends = data[0]["trends"]
        elif isinstance(data, dict) and "trends" in data:
            trends = data["trends"]
        elif isinstance(data, list):
            trends = data

        result_list = []
        for item in trends[:limit]:
            name = item.get("name", "未知趋势")
            volume = item.get("tweet_volume")
            score = f"🔥 {volume} Tweets" if volume else "🔥 热度飙升"
            
            # Twitter API 返回的 url 通常是 search link
            link = item.get("url") or f"https://twitter.com/search?q={name.replace('#', '%23')}"
            
            result_list.append({
                'title': name,
                'url': '',
                'permalink': link,
                'body': "当前 Twitter 实时热门趋势话题",
                'score': score
            })
        return result_list
    except Exception as e:
        print(f"抓取 Twitter 失败: {e}")
        return []

def fetch_youtube_trends(limit):
    """通过 RapidAPI 获取 YouTube 热门视频"""
    if not RAPIDAPI_KEY:
        print("❌ 未配置 RAPIDAPI_KEY，跳过 YouTube 抓取")
        return []

    url = "https://youtube138.p.rapidapi.com/v2/trending"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "youtube138.p.rapidapi.com"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        # 防御性解析：YouTube API 通常将视频列表放在 contents 中
        contents = data.get("contents", []) if isinstance(data, dict) else data
        
        result_list = []
        for item in contents:
            if len(result_list) >= limit:
                break
                
            # 解析嵌套结构
            video = item.get("video", item)
            title = video.get("title", "未知标题")
            video_id = video.get("videoId", "")
            stats = video.get("stats", {})
            views = stats.get("views") or "高播放量"
            
            link = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
            
            # 获取封面图
            thumbnails = video.get("thumbnails", [])
            img_url = thumbnails[0].get("url") if thumbnails else ""
            
            result_list.append({
                'title': title,
                'url': img_url,
                'permalink': link,
                'body': f"当前 YouTube 热门趋势视频，播放量：{views}",
                'score': f"▶️ {views} Views"
            })
        return result_list
    except Exception as e:
        print(f"抓取 YouTube 失败: {e}")
        return []

def fetch_reddit_posts(subreddit, time_filter, limit):
    """获取 Reddit 热帖并提取图片和正文"""
    url = f"https://www.reddit.com/r/{subreddit}/top.rss?t={time_filter}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 RSSReader/6.0'}

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
            
            img_url = ""
            post_body = ""
            
            if content is not None and content.text:
                img_match = re.search(r'href="(https://i\.redd\.it/[^"]+)"', content.text)
                if img_match:
                    img_url = img_match.group(1)
                
                raw_html = content.text
                clean_text = re.sub(r'<[^>]+>', ' ', html.unescape(raw_html))
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                post_body = clean_text[:500] 
            
            result_list.append({
                'title': title,
                'url': img_url,
                'permalink': link,
                'body': post_body,
                'score': '🔥 榜单前列'
            })
        return result_list
    except Exception as e:
        print(f"抓取 Reddit r/{subreddit} 失败: {e}")
        return []

def fetch_kym_news(limit):
    """获取 Know Your Meme 最新梗资讯"""
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
            
            img_url = ""
            post_body = ""
            
            if description:
                img_match = re.search(r'src="(https://i\.kym-cdn\.com/[^"]+)"', description)
                if img_match:
                    img_url = img_match.group(1)
                
                clean_text = re.sub(r'<[^>]+>', ' ', html.unescape(description))
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                post_body = clean_text[:500]
                
            result_list.append({
                'title': title,
                'url': img_url,
                'permalink': link,
                'body': post_body,
                'score': '📰 最新趋势'
            })
        return result_list
    except Exception as e:
        print(f"抓取 Know Your Meme 失败: {e}")
        return []

# ==========================================
# 3. AI 业务处理层
# ==========================================
def analyze_post_with_ai(title, source_name, body, img_url):
    """调用大模型，强制输出无表情符号的结构化纯文本"""
    if not AI_API_KEY:
         return "解析: 未配置 AI 密钥\n创意: 无法生成"

    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {AI_API_KEY}',
        'Content-Type': 'application/json'
    }

    system_prompt = "你是一个资深的海外游戏试玩广告策划。你的任务是解读海外全网热点（包含视频、社交话题），提取刺激点转化为买量创意。"
    
    text_prompt = f"""
    信息来源: {source_name}
    标题/话题: {title}
    正文/背景信息: {body if body else '无附加信息'}
    
    请结合上述信息（如果是视频或图片请结合相关语境推测），严格按照以下两行格式输出（总字数控制在100字以内，【绝不要】使用任何 Emoji 或特殊表情符号）：
    解析: (一句话解释这个话题/趋势/视频的核心情绪痛点、笑点或吸引力原理)
    创意: (一句话说明如何将其转化为试玩广告前3秒的画面、猎奇互动或剧情选项)
    """

    user_content = [{"type": "text", "text": text_prompt}]
    
    if img_url:
        user_content.append({"type": "image_url", "image_url": {"url": img_url}})

    payload = json.dumps({
        "model": "gemini-3.1-flash-lite-preview", 
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.7,
        "max_tokens": 150
    })

    try:
        response = requests.post(AI_API_URL, headers=headers, data=payload)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"AI 解析出错: {e}")
        return "解析: AI 深入解析失败\n创意: 请结合原文直达链接自行查看"

# ==========================================
# 4. 消息推送层
# ==========================================
def send_to_feishu(report_title, content_blocks):
    """构建分组分块的清晰飞书排版"""
    if not FEISHU_WEBHOOK_URL:
        print("❌ 未配置飞书 Webhook URL，无法推送。")
        return

    feishu_post_content = []
    
    # 统一定义渲染顺序和 UI
    section_config = {
        'twitter': "🐦 【 Twitter | 实时话题榜 】\n",
        'youtube': "▶️ 【 YouTube | 热门视频趋势 】\n",
        'kym': "🌐 【 Know Your Meme | 全网流行趋势 】\n",
        'reddit': "👾 【 Reddit | 垂直圈层热点 】\n"
    }

    for section_type, section_title in section_config.items():
        blocks_of_type = [b for b in content_blocks if b['type'] == section_type]
        if not blocks_of_type:
            continue
            
        feishu_post_content.append([{"tag": "text", "text": section_title}])
        
        for block in blocks_of_type:
            if section_type == 'reddit':
                feishu_post_content.append([{"tag": "text", "text": f"◼ {block['source']}"}])
            
            if not block['posts']:
                feishu_post_content.append([{"tag": "text", "text": "   暂无抓取到有效数据\n\n"}])
                continue
                
            for index, post in enumerate(block['posts'], start=1):
                feishu_post_content.append([{"tag": "text", "text": f"   {index}. {post['title']}  ({post['score']})"}])
                
                link_line = [{"tag": "text", "text": "      ↳ 链接: "}]
                if post['url']:
                    link_line.append({"tag": "a", "text": "[查看封面/视觉素材]", "href": post['url']})
                    link_line.append({"tag": "text", "text": " | "})
                if post['permalink']:
                    link_line.append({"tag": "a", "text": "[原文直达]", "href": post['permalink']})
                feishu_post_content.append(link_line)
                
                ai_lines = post['ai_analysis'].split('\n')
                for line in ai_lines:
                    clean_line = line.strip()
                    if clean_line:
                        clean_line = clean_line.replace("解析：", "解析: ").replace("创意：", "创意: ")
                        feishu_post_content.append([{"tag": "text", "text": f"      ▪ {clean_line}"}])
                
                feishu_post_content.append([{"tag": "text", "text": "\n"}])

    payload = {
        "msg_type": "post",
        "content": {"post": {"zh_cn": {"title": report_title, "content": feishu_post_content}}}
    }

    try:
        requests.post(FEISHU_WEBHOOK_URL, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        print("✅ 成功推送到飞书！排版已优化。")
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")

# ==========================================
# 5. 主程序控制中枢
# ==========================================
def main():
    target_subreddits = [
        'memes',
        'oddlysatisfying',
        'shittymobilegameads',
        'AmItheAsshole',
        'TikTokCringe',
        'tiktokgossip',
        'holdmybeer',
        'mildlyinteresting',
    ]

    today_weekday = datetime.today().weekday()
    if today_weekday == 0:
        report_title = "📊 [周一盘点] 海外全网热点与买量素材日报"
        time_filter = 'week'
        fetch_limit = 10
    else:
        report_title = "📰 [日常速递] 海外全网热点与买量素材日报"
        time_filter = 'day'
        fetch_limit = 3

    print(f"🎯 正在生成: {report_title}...\n")
    all_content_blocks = []

    # --- 1. 抓取 Twitter 趋势 ---
    print("正在抓取 Twitter 热点...")
    twitter_posts = fetch_twitter_trends(fetch_limit)
    if twitter_posts:
        for post in twitter_posts:
            print(f"  -> 正在解析 Twitter: {post['title']}...") 
            post['ai_analysis'] = analyze_post_with_ai(post['title'], "Twitter Trending", post['body'], post['url'])
        all_content_blocks.append({
            'type': 'twitter', 'source': 'Twitter US', 'posts': twitter_posts
        })
    time.sleep(1.5)

    # --- 2. 抓取 YouTube 趋势 ---
    print("正在抓取 YouTube 热点...")
    youtube_posts = fetch_youtube_trends(fetch_limit)
    if youtube_posts:
        for post in youtube_posts:
            print(f"  -> 正在解析 YouTube: {post['title'][:30]}...") 
            post['ai_analysis'] = analyze_post_with_ai(post['title'], "YouTube Trending", post['body'], post['url'])
        all_content_blocks.append({
            'type': 'youtube', 'source': 'YouTube US', 'posts': youtube_posts
        })
    time.sleep(1.5)

    # --- 3. 抓取 Know Your Meme ---
    print("正在抓取 Know Your Meme 趋势...")
    kym_posts = fetch_kym_news(fetch_limit)
    if kym_posts:
        for post in kym_posts:
            print(f"  -> 正在解析 KYM: {post['title'][:30]}...") 
            post['ai_analysis'] = analyze_post_with_ai(post['title'], "Know Your Meme", post['body'], post['url'])
        all_content_blocks.append({
            'type': 'kym', 'source': 'Know Your Meme', 'posts': kym_posts
        })
    time.sleep(1.5)

    # --- 4. 抓取 Reddit ---
    for sub in target_subreddits:
        print(f"正在抓取 r/{sub} ...")
        posts = fetch_reddit_posts(sub, time_filter, fetch_limit)
        if posts:
            for post in posts:
                print(f"  -> 正在解析 Reddit r/{sub}: {post['title'][:30]}...") 
                post['ai_analysis'] = analyze_post_with_ai(post['title'], f"r/{sub}", post['body'], post['url'])
            all_content_blocks.append({
                'type': 'reddit', 'source': f"r/{sub}", 'posts': posts
            })
        time.sleep(1.5)
        
    print("\n📦 数据处理完毕，正在推送到飞书...")
    send_to_feishu(report_title, all_content_blocks)

if __name__ == "__main__":
    main()