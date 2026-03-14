import os
import requests
from datetime import datetime
import time
import json
import xml.etree.ElementTree as ET
import re
import html # 新增：用于清洗网页标签

# ==========================================
# 1. 核心配置区 (通过 GitHub Secrets 注入环境变量)
# ==========================================
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL")
AI_API_KEY = os.environ.get("AI_API_KEY") 
AI_API_URL = "https://api.bltcy.ai/v1/chat/completions"


# ==========================================
# 2. 数据获取层 (RSS 降维打击 + 正文/图片提取)
# ==========================================
def fetch_reddit_posts(subreddit, time_filter, limit):
    """使用 RSS 订阅源获取 Reddit 热帖，并提取图片和正文"""
    url = f"https://www.reddit.com/r/{subreddit}/top.rss?t={time_filter}"
    
    # 伪装成常见的 RSS 阅读器
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 RSSReader/2.0'
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        # 解析 RSS (Atom 格式) 的 XML 数据
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
                # 1. 提取 Reddit 原生图片直链
                img_match = re.search(r'href="(https://i\.redd\.it/[^"]+)"', content.text)
                if img_match:
                    img_url = img_match.group(1)
                
                # 2. 清洗 HTML 标签，提取纯文本正文（针对 AITA 等故事长文贴）
                raw_html = content.text
                clean_text = re.sub(r'<[^>]+>', ' ', html.unescape(raw_html))
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                # 只取前 500 个字符，足够 AI 把握核心冲突，又节省 Token 成本
                post_body = clean_text[:500] 
            
            result_list.append({
                'title': title,
                'score': '🔥榜单前列',
                'url': img_url,
                'permalink': link,
                'body': post_body # 将清洗后的正文存入数据字典
            })
            
        return result_list
        
    except Exception as e:
        print(f"抓取 r/{subreddit} 失败: {e}")
        return []


# ==========================================
# 3. AI 业务处理层 (多模态：图文混合解析)
# ==========================================
def analyze_post_with_ai(title, subreddit, body, img_url):
    """调用大模型，结合标题、正文背景甚至图片进行深度解析"""
    if not AI_API_KEY:
         return f"⚠️ 未配置 AI 密钥，原标题: {title}"

    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {AI_API_KEY}',
        'User-Agent': 'DMXAPI/1.0.0',
        'Content-Type': 'application/json'
    }

    system_prompt = "你是一个资深的海外游戏试玩广告（Playable Ads）策划。你的任务是深入理解Reddit热帖（包括标题、正文背景和图片内容），并提取其核心刺激点转化为广告创意。"
    
    text_prompt = f"""
    板块来源: r/{subreddit}
    帖子标题: {title}
    帖子正文/背景信息: {body if body else '无正文'}
    
    请结合上述背景（如果是梗图，请结合图片内容），严格按照以下两点输出（总字数控制在100字以内）：
    1. 📝 解析：(一句话解释这个梗/故事的核心笑点、痛点或抓马元素)
    2. 💡 创意：(一句话说明如何将此转化为试玩广告前3秒的画面、互动或二选一选项)
    """

    # 构建支持多模态（视觉+文本）的请求体
    user_content = [{"type": "text", "text": text_prompt}]
    
    # 如果抓取到了图片，就让 AI “开眼”看图
    if img_url:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": img_url}
        })

    payload = json.dumps({
        "model": "gemini-3.1-flash-lite-preview", # 使用你指定的强大轻量模型
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
        # 如果图文解析失败，至少返回原标题，保证流程不中断
        return f"AI深入解析失败，仅提供标题参考: {title}"


# ==========================================
# 4. 消息推送层 (组装富文本发送飞书)
# ==========================================
def send_to_feishu(report_title, content_blocks):
    """将整合好的数据以富文本形式发送到飞书"""
    if not FEISHU_WEBHOOK_URL:
        print("❌ 未配置飞书 Webhook URL，无法推送。")
        return

    feishu_post_content = []
    
    for block in content_blocks:
        subreddit = block['subreddit']
        posts = block['posts']
        
        feishu_post_content.append([{"tag": "text", "text": f"🔥 【r/{subreddit}】", "un_escape": True}])
        
        if not posts:
            feishu_post_content.append([{"tag": "text", "text": "  暂无抓取到有效数据\n"}])
            continue
            
        for index, post in enumerate(posts, start=1):
            link_line = [{"tag": "text", "text": f"[{index}] 热度: {post['score']} | "}]
            if post['url']:
                link_line.append({"tag": "a", "text": "[查看视觉素材]", "href": post['url']})
                link_line.append({"tag": "text", "text": " | "})
            link_line.append({"tag": "a", "text": "[Reddit原贴]", "href": post['permalink']})
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
        'dankmemes',
        'holdmybeer',
        'oddlysatisfying',
        'mildlyinfuriating',
        'shittymobilegameads',
        'AmItheAsshole',
    ]

    today_weekday = datetime.today().weekday()
    
    if today_weekday == 0:
        report_title = "📊 [周一盘点] 海外爆款素材与AI深度解析 Top 10"
        time_filter = 'week'
        fetch_limit = 10
    else:
        report_title = f"🚀 [日常速递] 海外爆款素材与AI深度解析 Top 3"
        time_filter = 'day'
        fetch_limit = 3

    print(f"🎯 正在生成: {report_title}...\n")
    all_content_blocks = []

    for sub in target_subreddits:
        print(f"正在抓取 r/{sub} ...")
        
        posts = fetch_reddit_posts(sub, time_filter, fetch_limit)
        
        for post in posts:
            print(f"  -> 正在使用 Gemini 解析: {post['title'][:30]}...") 
            # 传入新增的 body 和 url 参数，激活多模态能力
            post['ai_analysis'] = analyze_post_with_ai(
                post['title'], 
                sub, 
                post['body'], 
                post['url']
            )
            
        all_content_blocks.append({
            'subreddit': sub,
            'posts': posts
        })
        
        time.sleep(1.5)
        
    print("\n📦 数据抓取与AI处理完毕，正在推送到飞书...")
    send_to_feishu(report_title, all_content_blocks)

if __name__ == "__main__":
    main()