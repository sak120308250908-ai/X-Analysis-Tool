import pandas as pd
import sys

if len(sys.argv) < 2:
    print("Usage: python3 analyze_tweets_any.py <csv_filename>")
    sys.exit(1)

filename = sys.argv[1]
df = pd.read_csv(filename)

df['Engagement'] = df['Likes'] + df['Retweets'] * 2 + df['Replies'] * 3
print("Total tweets analyzed:", len(df))

media_eng = df.groupby('MediaCount')['Engagement'].agg(['mean', 'count'])
print("\n=== Avg Engagement by Media Count ===")
print(media_eng)

df['Date'] = pd.to_datetime(df['Date'], format='%a %b %d %H:%M:%S +0000 %Y')
df['JST_Date'] = df['Date'] + pd.Timedelta(hours=9)
df['Hour'] = df['JST_Date'].dt.hour
hour_eng = df.groupby('Hour')['Engagement'].agg(['mean', 'count']).sort_values(by='mean', ascending=False).head(5)
print("\n=== Top 5 JST Hours for Engagement ===")
print(hour_eng)

print("\n=== Top 5 Posts ===")
top_tweets = df.sort_values(by='Engagement', ascending=False).head(5)
for idx, row in top_tweets.iterrows():
    print(f"[{row['JST_Date']}] Likes: {row['Likes']}, URL: {row['URL']}")
    print(f"Text: {str(row['Text'])[:80]}...\n")
