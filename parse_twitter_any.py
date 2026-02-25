import json
import urllib.request
import urllib.error
import re
import csv
import sys

def fetch_tweets(screen_name, cursor=None):
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{screen_name}"
    if cursor:
        url += f"?cursor={cursor}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">({.*?})</script>', html)
        if not match:
            return [], None
            
        json_data = json.loads(match.group(1))
        entries = json_data['props']['pageProps']['timeline']['entries']
        tweets = [e for e in entries if e['type'] == 'tweet']
        
        bottom_cursor = None
        cursors = [e for e in entries if e['type'] == 'timeline_cursor']
        for c in cursors:
            if c['content']['cursorType'] == 'Bottom':
                bottom_cursor = c['content']['value']
                
        return tweets, bottom_cursor
    except Exception as e:
        print(f"Error fetching: {e}")
        return [], None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 parse_twitter_any.py <screen_name>")
        sys.exit(1)
        
    target_user = sys.argv[1]
    all_tweets = []
    current_cursor = None
    print(f"Fetching tweets for @{target_user}...")
    
    for i in range(10):  # Fetch up to ~200 tweets
        print(f"Fetching page {i+1}...")
        tweets, next_cursor = fetch_tweets(target_user, current_cursor)
        all_tweets.extend(tweets)
        
        if not next_cursor or next_cursor == current_cursor:
            break
        current_cursor = next_cursor

    unique_tweets = {t['content']['tweet']['id_str']: t for t in all_tweets}.values()
    print(f"Found {len(unique_tweets)} unique tweets.")
    
    if len(unique_tweets) > 0:
        filename = f"{target_user}_tweets.csv"
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['DataIndex', 'Date', 'Likes', 'Retweets', 'Replies', 'Quotes', 'MediaCount', 'URL', 'Text'])
            for idx, t in enumerate(unique_tweets):
                tw = t['content']['tweet']
                date_str = tw.get('created_at', '')
                likes = tw.get('favorite_count', 0)
                rts = tw.get('retweet_count', 0)
                replies = tw.get('reply_count', 0)
                quotes = tw.get('quote_count', 0)
                text = tw.get('full_text', tw.get('text', '')).replace('\n', ' ')
                media = tw.get('entities', {}).get('media', [])
                media_ext = tw.get('extended_entities', {}).get('media', [])
                media_count = max(len(media), len(media_ext))
                url = f"https://x.com/{target_user}/status/{tw.get('id_str', '')}"
                writer.writerow([idx, date_str, likes, rts, replies, quotes, media_count, url, text])
        print(f"Saved to {filename}")
