import os
import requests
import cloudscraper # 新增：破盾神器
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

# ==========================================
# 2. 数据获取层 (Reddit RSS + KYM Cloudscraper)
# ==========================================
def fetch_reddit_posts(subreddit, time_filter, limit):
    """获取 Reddit 热帖"""
    url = f"https://www.reddit.com/r/{subreddit}/top.rss?t={time_filter}"
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 RSSReader/2.0'}

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
                'score': '🔥榜单前列',
                'url': img_url,
                'permalink': link,
                'body': post_body
            })
        return result_list
    except Exception as e:
        print(f"抓取 Reddit r/{subreddit} 失败: {e}")
        return []

def fetch_kym_news(limit):
    """使用 cloudscraper 穿透防线获取 Know Your Meme 最新梗资讯"""
    url = "https://knowyourmeme.com/news.rss"
    
    # 实例化破盾器，模拟真实桌面端 Chrome
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

    try:
        response = scraper.get(url)
        response.raise_for_status()
        
        # KYM 使用的是标准 RSS 2.0 格式，和 Reddit 的 Atom 格式略有不同
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
                # 提取 KYM 文章中的封面图 (通常在 src 属性中)
                img_match = re.search(r'src="(https://i\.kym-cdn\.com/[^"]+)"', description)
                if img_match:
                    img_url = img_match.group(1)
                
                # 清洗 HTML 获取纯文本简述
                clean_text = re.sub(r'<[^>]+>', ' ', html.unescape(description))
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                post_body = clean_text[:500]
                
            result_list.append({
                'title': title,
                'score': '📰 最新趋势', 
                'url': img_url,
                'permalink': link,
                'body': post_body
            })
            
        return result_list
    except Exception as e:
        print(f"抓取 Know Your Meme 失败: {e}")
        return []

# ==========================================
# 3. AI 业务处理层 (微调了 Prompt，兼容多信息源)
# ==========================================
def analyze_post_with_ai(title, source_name, body, img_url):
    """调用大模型，结合图文进行深度解析"""
    if not AI_API_KEY:
         return f"⚠️ 未配置 AI 密钥，原标题: {title}"

    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {AI_API_KEY}',
        'Content-Type': 'application/json'
    }

    system_prompt = "你是一个资深的海外游戏试玩广告（Playable Ads）策划。你的任务是深入理解海外网络热点（如Reddit热帖、KYM热梗），提取其核心刺激点转化为买量广告创意。"
    
    text_prompt = f"""
    信息来源: {source_name}
    标题: {title}
    正文/背景信息: {body if body else '无正文'}
    
    请结合上述背景（如果有梗图，请结合图片内容），严格按照以下两点输出（总字数控制在100字以内）：
    1. 📝 解析：(一句话解释这个梗/趋势的核心笑点、痛点或心理学原理)
    2. 💡 创意：(一句话说明如何将其转化为试玩广告前3秒的画面、互动套路或二选一选项)
    """

    user_content = [{"type": "text", "text": text_prompt}]
    
    if img_url:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": img_url}
        })

    payload = json.dumps({
        "model": "gemini-3.1-flash-lite-preview", 
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.7,
        "max_tokens": 200
    })

    try:
        response = requests.post(AI_API_URL, headers=headers, data=payload)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"AI 解析出错: {e}")
        return f"AI深入解析失败，仅提供标题参考: {title}"

# ==========================================
# 4. 消息推送层
# ==========================================
def send_to_feishu(report_title, content_blocks):
    """发送富文本到飞书"""
    if not FEISHU_WEBHOOK_URL:
        print("❌ 未配置飞书 Webhook URL，无法推送。")
        return

    feishu_post_content = []
    
    for block in content_blocks:
        source = block['source']
        posts = block['posts']
        
        # 区分一下来源的 Emoji 样式
        icon = "🔥" if "r/" in source else "🧠"
        feishu_post_content.append([{"tag": "text", "text": f"{icon} 【{source}】", "un_escape": True}])
        
        if not posts:
            feishu_post_content.append([{"tag": "text", "text": "  暂无抓取到有效数据\n"}])
            continue
            
        for index, post in enumerate(posts, start=1):
            link_line = [{"tag": "text", "text": f"[{index}] {post['score']} | "}]
            if post['url']:
                link_line.append({"tag": "a", "text": "[查看视觉素材]", "href": post['url']})
                link_line.append({"tag": "text", "text": " | "})
            link_line.append({"tag": "a", "text": "[原文直达]", "href": post['permalink']})
            feishu_post_content.append(link_line)
            
            feishu_post_content.append([{"tag": "text", "text": f"🤖 {post['ai_analysis']}"}])
            feishu_post_content.append([{"tag": "text", "text": "\n"}])

    payload = {
        "msg_type": "post",
        "content": {"post": {"zh_cn": {"title": report_title, "content": feishu_post_content}}}
    }

    try:
        requests.post(FEISHU_WEBHOOK_URL, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        print("✅ 成功推送到飞书！")
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
    ]

    today_weekday = datetime.today().weekday()
    
    if today_weekday == 0:
        report_title = "📊 [周一盘点] 海外热梗与广告创意库 Top 10"
        time_filter = 'week'
        fetch_limit = 10
    else:
        report_title = f"🚀 [日常速递] 海外热梗与广告创意库 Top 3"
        time_filter = 'day'
        fetch_limit = 3

    print(f"🎯 正在生成: {report_title}...\n")
    all_content_blocks = []

    # 1. 抓取 Know Your Meme (新增)
    print("正在抓取 Know Your Meme 趋势...")
    kym_posts = fetch_kym_news(fetch_limit)
    for post in kym_posts:
        print(f"  -> 正在使用 Gemini 解析 KYM: {post['title'][:30]}...") 
        post['ai_analysis'] = analyze_post_with_ai(post['title'], "Know Your Meme", post['body'], post['url'])
    
    all_content_blocks.append({
        'source': 'Know Your Meme (TikTok/Twitter趋势)',
        'posts': kym_posts
    })
    time.sleep(1.5)

    # 2. 抓取 Reddit 各大板块
    for sub in target_subreddits:
        print(f"正在抓取 r/{sub} ...")
        posts = fetch_reddit_posts(sub, time_filter, fetch_limit)
        
        for post in posts:
            print(f"  -> 正在使用 Gemini 解析 Reddit: {post['title'][:30]}...") 
            post['ai_analysis'] = analyze_post_with_ai(post['title'], f"r/{sub}", post['body'], post['url'])
            
        all_content_blocks.append({
            'source': f"r/{sub}",
            'posts': posts
        })
        time.sleep(1.5)
        
    print("\n📦 数据抓取与AI处理完毕，正在推送到飞书...")
    send_to_feishu(report_title, all_content_blocks)

if __name__ == "__main__":
    main()