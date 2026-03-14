import os
import requests
from datetime import datetime
import time
import json
import xml.etree.ElementTree as ET
import re

# ==========================================
# 1. 核心配置区 (通过 GitHub Secrets 注入环境变量)
# ==========================================
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL")
AI_API_KEY = os.environ.get("AI_API_KEY") 
AI_API_URL = "https://api.bltcy.ai/v1/chat/completions"


# ==========================================
# 2. 数据获取层 (RSS 降维打击方案)
# ==========================================
def fetch_reddit_posts(subreddit, time_filter, limit):
    """使用 RSS 订阅源绕过 API 限制获取 Reddit 热帖"""
    url = f"https://www.reddit.com/r/{subreddit}/top.rss?t={time_filter}"
    
    # 伪装成常见的 RSS 阅读器，进一步降低风控概率
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 RSSReader/1.0'
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        # 解析 RSS (Atom 格式) 的 XML 数据
        root = ET.fromstring(response.content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'} # Reddit 使用 Atom 命名空间
        
        entries = root.findall('atom:entry', ns)
        
        result_list = []
        for entry in entries[:limit]: # 只截取我们需要的前几名
            # 提取标题和原帖链接
            title = entry.find('atom:title', ns).text
            link = entry.find('atom:link', ns).attrib['href']
            
            # 尝试使用正则表达式从 RSS 内容中提取图片直链
            content = entry.find('atom:content', ns)
            img_url = ""
            if content is not None and content.text:
                img_match = re.search(r'href="(https://i\.redd\.it/[^"]+)"', content.text)
                if img_match:
                    img_url = img_match.group(1)
            
            result_list.append({
                'title': title,
                'score': '🔥榜单前列', # RSS 不返回具体分数，用统一文案替代
                'url': img_url,
                'permalink': link
            })
            
        return result_list
        
    except Exception as e:
        print(f"抓取 r/{subreddit} 失败: {e}")
        return []


# ==========================================
# 3. AI 业务处理层 (调用 Gemini 提炼创意)
# ==========================================
def analyze_post_with_ai(title, subreddit):
    """调用大模型对英文标题进行翻译、解析和广告创意转化"""
    if not AI_API_KEY:
         return f"⚠️ 未配置 AI 密钥，原标题: {title}"

    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {AI_API_KEY}',
        'User-Agent': 'DMXAPI/1.0.0',
        'Content-Type': 'application/json'
    }

    system_prompt = "你是一个资深的海外游戏试玩广告（Playable Ads）策划。你的任务是解读Reddit上的英文热帖，并将其转化为广告创意。"
    user_prompt = f"""
    板块来源: r/{subreddit}
    帖子标题: {title}
    
    请用极其简练的语言，严格按照以下两点输出（总字数控制在80字以内）：
    1. 📝 解析：(一句话翻译标题，并解释其中的笑点/痛点/抓马元素)
    2. 💡 创意：(一句话说明如何将这个梗转化为试玩广告前3秒的画面或互动选项)
    """

    payload = json.dumps({
        "model": "gemini-3.1-flash-lite-preview", # 使用你指定的超快轻量模型
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
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
        return f"AI解析失败，原标题: {title}"


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
            # 链接行排版
            link_line = [{"tag": "text", "text": f"[{index}] 热度: {post['score']} | "}]
            if post['url']:
                link_line.append({"tag": "a", "text": "[查看视觉素材]", "href": post['url']})
                link_line.append({"tag": "text", "text": " | "})
            link_line.append({"tag": "a", "text": "[Reddit原贴]", "href": post['permalink']})
            feishu_post_content.append(link_line)
            
            # AI 结果排版
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

    # 根据日期决定抓取策略
    today_weekday = datetime.today().weekday()
    
    if today_weekday == 0:
        report_title = "📊 [周一盘点] 海外爆款素材与AI解析 Top 10"
        time_filter = 'week'
        fetch_limit = 10
    else:
        report_title = f"🚀 [日常速递] 海外爆款素材与AI解析 Top 3"
        time_filter = 'day'
        fetch_limit = 3

    print(f"🎯 正在生成: {report_title}...\n")
    all_content_blocks = []

    for sub in target_subreddits:
        print(f"正在抓取并由AI解析 r/{sub} ...")
        
        # 抓取 RSS 数据
        posts = fetch_reddit_posts(sub, time_filter, fetch_limit)
        
        # 遍历处理每一条帖子
        for post in posts:
            print(f"  -> 正在使用 Gemini 解析: {post['title'][:30]}...") 
            post['ai_analysis'] = analyze_post_with_ai(post['title'], sub)
            
        all_content_blocks.append({
            'subreddit': sub,
            'posts': posts
        })
        
        # 稍微休眠，给目标服务器喘口气
        time.sleep(1.5)
        
    print("\n📦 数据抓取与AI处理完毕，正在推送到飞书...")
    send_to_feishu(report_title, all_content_blocks)

if __name__ == "__main__":
    main()