import os
import requests
from datetime import datetime
import time
import json

# ---------------- 配置区 (通过环境变量读取，保护隐私) ----------------
# 在 GitHub Actions 中，需要配置这两个 Secrets
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL")
AI_API_KEY = os.environ.get("AI_API_KEY") 

# 中转站的固定接口地址
AI_API_URL = "https://api.bltcy.ai/v1/chat/completions"
# -------------------------------------------------------------------

def fetch_reddit_posts(subreddit, time_filter, limit):
    """请求 Reddit 指定板块的 Top 帖子"""
    url = f"https://www.reddit.com/r/{subreddit}/top.json"
    params = {'t': time_filter, 'limit': limit}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 AdCreativeBot/4.0'
    }

    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        posts = data['data']['children']
        
        result_list = []
        for post in posts:
            post_data = post['data']
            if not post_data.get('is_video_ad') and not post_data.get('stickied'):
                result_list.append({
                    'title': post_data.get('title'),
                    'score': post_data.get('score'),
                    'url': post_data.get('url'),
                    'permalink': f"https://www.reddit.com{post_data.get('permalink')}"
                })
        return result_list
    except Exception as e:
        print(f"抓取 r/{subreddit} 失败: {e}")
        return []

def analyze_post_with_ai(title, subreddit):
    """使用中转站 API 调用 Gemini 模型对英文标题进行解析"""
    if not AI_API_KEY:
         return f"未配置AI密钥，原标题: {title}"

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
        "model": "gemini-3.1-flash-lite-preview",
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
        
        # 解析返回的 JSON 数据
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
        
    except Exception as e:
        print(f"AI 解析出错: {e}")
        return f"AI解析失败，原标题: {title}"

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
        report_title = "📊 [周一盘点] 海外爆款素材与AI解析 Top 10"
        time_filter = 'week'
        fetch_limit = 10
    else:
        report_title = f"🚀 [日常速递] 海外爆款素材与AI解析 Top 3"
        time_filter = 'day'
        fetch_limit = 3

    print(f"正在生成: {report_title}...")
    all_content_blocks = []

    for sub in target_subreddits:
        print(f"正在抓取并由AI解析 r/{sub} ...")
        posts = fetch_reddit_posts(sub, time_filter, fetch_limit)
        
        for post in posts:
            print(f"  -> 正在使用大模型解析: {post['title'][:30]}...") 
            post['ai_analysis'] = analyze_post_with_ai(post['title'], sub)
            
        all_content_blocks.append({
            'subreddit': sub,
            'posts': posts
        })
        time.sleep(1.5)
        
    print("数据抓取与AI处理完毕，正在推送到飞书...")
    send_to_feishu(report_title, all_content_blocks)

if __name__ == "__main__":
    main()