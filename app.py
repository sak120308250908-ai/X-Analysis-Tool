import streamlit as st
import pandas as pd
import urllib.request
import urllib.error
import re
import json
from datetime import datetime, timedelta

st.set_page_config(page_title="X (Twitter) アカウント分析ツール", layout="wide")

st.title("📊 X (Twitter) アカウント分析ツール")
st.write("アカウントIDを入力するだけで、直近の投稿データを取得・分析し、エンゲージメントの傾向を可視化します。")

# --- Fetch Logic ---
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
    except urllib.error.HTTPError as e:
        if e.code == 429:
            st.session_state.rate_limit_until = datetime.now() + timedelta(minutes=15)
            st.rerun()
        else:
            st.error(f"データ取得エラー（サーバーエラー）: {e.code} - {e.reason}")
        return [], None
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
        return [], None

# --- State Management ---
if 'df' not in st.session_state:
    st.session_state.df = None
if 'analysis_target' not in st.session_state:
    st.session_state.analysis_target = None
if 'top_tweets' not in st.session_state:
    st.session_state.top_tweets = None
if 'hour_eng' not in st.session_state:
    st.session_state.hour_eng = None
if 'rate_limit_until' not in st.session_state:
    st.session_state.rate_limit_until = None

# --- UI ---
target_user = st.text_input("🔍 XのアカウントIDを入力してください（@は不要です）", placeholder="elonmusk", value="")

is_rate_limited = False
if st.session_state.rate_limit_until:
    if datetime.now() < st.session_state.rate_limit_until:
        is_rate_limited = True
        wait_until_str = st.session_state.rate_limit_until.strftime("%H:%M:%S")
        st.error(f"🚨 現在X側でアクセス制限がかかっています。{wait_until_str} 以降に再度お試しください。")
        st.info("※データ取得ボタンは制限解除まで一時的に無効化されています。")
    else:
        st.session_state.rate_limit_until = None

if st.button("データ取得・分析開始", type="primary", disabled=is_rate_limited):
    if not target_user:
        st.warning("アカウントIDを入力してください。")
    else:
        with st.spinner(f"@{target_user} のデータを取得しています...（最大約100件）"):
            all_tweets = []
            current_cursor = None
            
            for i in range(10):  # Fetch up to ~200 tweets
                tweets, next_cursor = fetch_tweets(target_user, current_cursor)
                all_tweets.extend(tweets)
                if not next_cursor or next_cursor == current_cursor:
                    break
                current_cursor = next_cursor

            unique_tweets = {t['content']['tweet']['id_str']: t for t in all_tweets}.values()
            
            if len(unique_tweets) == 0:
                st.error("ツイートが見つかりませんでした。IDが間違っているか、非公開アカウントの可能性があります。")
                st.session_state.df = None
            else:
                st.success(f"{len(unique_tweets)}件のツイートを取得しました！")
                
                # --- Convert to DataFrame ---
                data = []
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
                    data.append({
                        'Date': date_str,
                        'Likes': likes,
                        'Retweets': rts,
                        'Replies': replies,
                        'Quotes': quotes,
                        'MediaCount': media_count,
                        'URL': url,
                        'Text': text
                    })
                
                df = pd.DataFrame(data)
                df['Engagement'] = df['Likes'] + df['Retweets'] * 2 + df['Replies'] * 3
                
                # 時間変換
                df['Date'] = pd.to_datetime(df['Date'], format='%a %b %d %H:%M:%S +0000 %Y')
                df['JST_Date'] = df['Date'] + pd.Timedelta(hours=9)
                df['Hour'] = df['JST_Date'].dt.hour
                
                # Save to session state
                st.session_state.df = df
                st.session_state.analysis_target = target_user

# --- Render Analysis if DataFrame exists in session ---
if st.session_state.df is not None:
    df = st.session_state.df
    target_user = st.session_state.analysis_target
    
    # --- Analysis Display ---
    st.markdown("---")
    st.header(f"📈 @{target_user} のエンゲージメント分析レポート")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("取得ツイート数", f"{len(df)}件")
    col2.metric("平均エンゲージメントスコア", f"{int(df['Engagement'].mean())}")
    col3.metric("最高エンゲージメントスコア", f"{int(df['Engagement'].max())}")
    
    st.markdown("---")
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        st.subheader("⏰ 時間帯別の平均エンゲージメント")
        hour_eng = df.groupby('Hour')['Engagement'].mean().reset_index()
        # 時間帯を0-23時まで全て表示するための補完
        all_hours = pd.DataFrame({'Hour': range(24)})
        hour_eng = pd.merge(all_hours, hour_eng, on='Hour', how='left').fillna(0)
        st.session_state.hour_eng = hour_eng # Store for AI
        st.bar_chart(hour_eng.set_index('Hour'))
        st.caption("※棒が高い時間帯に投稿すると伸びやすい傾向があります（日本時間）")
    
    with col_chart2:
        st.subheader("🖼 画像・動画の枚数による差")
        media_eng = df.groupby('MediaCount')['Engagement'].mean().reset_index()
        media_eng['MediaCount'] = media_eng['MediaCount'].astype(str) + "枚"
        st.bar_chart(media_eng.set_index('MediaCount'))
        st.caption("※何枚の画像を添付した投稿が一番反響があるかが分かります")
    
    # --- Keyword Analysis ---
    st.markdown("---")
    st.subheader("🔑 エンゲージメントが増えやすいキーワードTOP10")
    
    with st.spinner("キーワードを抽出・分析しています..."):
        try:
            from janome.tokenizer import Tokenizer
            from collections import defaultdict
            import re

            t = Tokenizer()
            keyword_eng = defaultdict(list)
            
            stop_words = {'これ', 'それ', 'あれ', 'この', 'その', 'あの', 'ここ', 'そこ', 'あそこ', 'ため', 'こと', 'もの', 'よう', 'わけ', 'はず', 'さん', 'ちゃん', 'くん', 'たち', '今日', '明日', '昨日', '今回', 'みなさん', '皆様'}
            
            for idx, row in df.iterrows():
                # Remove URLs and Mentions
                text = re.sub(r'http\S+|@\S+', '', str(row['Text']))
                tokens = t.tokenize(text)
                words = set()
                
                for token in tokens:
                    part_of_speech = token.part_of_speech.split(',')[0]
                    word = token.base_form
                    
                    # 名詞のみ、1文字除外、ストップワード除外、記号除外
                    if part_of_speech == '名詞' and len(word) > 1 and word not in stop_words and re.match(r'^[^\W_]+$', word, re.UNICODE):
                        words.add(word)
                
                for w in words:
                    keyword_eng[w].append(row['Engagement'])
            
            kw_stats = []
            for kw, engs in keyword_eng.items():
                if len(engs) >= 2: # 最低2回以上使われている単語に限定
                    kw_stats.append({
                        "キーワード": kw,
                        "平均エンゲージメント": int(sum(engs) / len(engs)),
                        "出現回数": len(engs)
                    })
            
            if kw_stats:
                df_kw = pd.DataFrame(kw_stats)
                df_kw = df_kw.sort_values(by="平均エンゲージメント", ascending=False).head(10)
                
                # テーブルとグラフで表示
                col_kw1, col_kw2 = st.columns([1, 1.5])
                with col_kw1:
                    st.dataframe(df_kw.set_index("キーワード"))
                with col_kw2:
                    st.bar_chart(df_kw.set_index("キーワード")["平均エンゲージメント"])
                    
                st.caption("※2回以上投稿で使用された名詞の中から、平均スコアが高いTOP10を抽出しています。")
            else:
                st.write("有効なキーワードデータが不足しています（共通の単語が少ない可能性があります）。")
                
        except ImportError:
            st.error("キーワード抽出の準備中（janomeライブラリをインストール中）です。数秒後に再度お試しください。")

    # --- Specific Keyword Analysis ---
    st.markdown("---")
    st.subheader("🎯 特定キーワードのエンゲージメント比較")
    st.write("指定したキーワードが含まれる投稿と、含まれない投稿で反響にどのくらい差があるかを比較します。")
    
    specific_keyword = st.text_input("比較したいキーワードを入力してください", placeholder="新台")
    
    if specific_keyword:
        df_with_kw = df[df['Text'].str.contains(specific_keyword, case=False, na=False)]
        df_without_kw = df[~df['Text'].str.contains(specific_keyword, case=False, na=False)]
        
        if len(df_with_kw) == 0:
            st.warning(f"「{specific_keyword}」が含まれるツイートは見つかりませんでした。")
        else:
            col_kw_comp1, col_kw_comp2 = st.columns(2)
            
            with col_kw_comp1:
                st.markdown(f"**✅ 「{specific_keyword}」を含む投稿 ({len(df_with_kw)}件)**")
                st.metric("平均スコア", f"{int(df_with_kw['Engagement'].mean())}")
                st.metric("平均いいね数", f"{int(df_with_kw['Likes'].mean())}")
                st.metric("平均RT数", f"{int(df_with_kw['Retweets'].mean())}")
                
            with col_kw_comp2:
                st.markdown(f"**❌ 含まれない投稿 ({len(df_without_kw)}件)**")
                if len(df_without_kw) > 0:
                    st.metric("平均スコア", f"{int(df_without_kw['Engagement'].mean())}")
                    st.metric("平均いいね数", f"{int(df_without_kw['Likes'].mean())}")
                    st.metric("平均RT数", f"{int(df_without_kw['Retweets'].mean())}")
                else:
                    st.write("比較対象データがありません")
            
            comp_data = pd.DataFrame({
                "状態": [f"「{specific_keyword}」あり", f"なし"],
                "平均スコア": [
                    int(df_with_kw['Engagement'].mean()) if len(df_with_kw)>0 else 0,
                    int(df_without_kw['Engagement'].mean()) if len(df_without_kw)>0 else 0
                ]
            })
            st.bar_chart(comp_data.set_index("状態"))
                
# --- AI Summary ---
    st.markdown("---")
    st.subheader("🤖 AIによるアカウント総評・分析コメント")
    
    # We need an API key to run Gemini. Let user input it if they want the AI summary.
    api_key = st.text_input("Gemini APIキーを入力してください（無料枠で取得可能です）", type="password")
    
    if st.button("AIに独自の分析を依頼する"):
        if not api_key:
            st.warning("APIキーを入力してください。")
        else:
            with st.spinner("AIがデータを読み込み、独自の視点で分析レポートを作成しています...（約10〜20秒）"):
                try:
                    from google import genai
                    client = genai.Client(api_key=api_key)
                    
                    # Prepare context for the prompt
                    top_tweets = df.sort_values(by='Engagement', ascending=False)
                    top_posts_text = "\n".join([f"- いいね:{r['Likes']}, RT:{r['Retweets']}, 本文:{str(r['Text'])[:100]}" for _, r in top_tweets.head(5).iterrows()])
                    prompt = f'''
                    以下はX（Twitter）アカウント「@{target_user}」の直近の投稿データを分析した結果です。
                    あなたはプロのSNSマーケターとして、このデータに基づいた「総評」と「今後エンゲージメントを伸ばすためのアドバイス」を400文字程度で分かりやすくまとめてください。

                    【データ概要】
                    - 取得ツイート数: {len(df)}件
                    - 平均エンゲージメントスコア: {int(df['Engagement'].mean())}
                    
                    【バズりやすい時間帯トップ3】
                    {st.session_state.hour_eng.sort_values(by='Engagement', ascending=False).head(3)['Hour'].tolist()}時台
                    
                    【反響が大きかったトップ5の投稿内容】
                    {top_posts_text}

                    上記を踏まえ、「このアカウント特有の強み・特徴」と「具体的な今後のアクション」を論理的に出力してください。
                    '''
                    
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=prompt,
                    )
                    
                    st.info(response.text)
                    
                except Exception as e:
                    st.error(f"AI分析中にエラーが発生しました: {e}")

    st.markdown("---")
    st.subheader("🔥 エンゲージメントTOP 5 投稿")
    top_tweets = df.sort_values(by='Engagement', ascending=False).head(5)
    for idx, row in top_tweets.iterrows():
        with st.expander(f"👑 スコア: {int(row['Engagement'])} | いいね: {row['Likes']} | RT: {row['Retweets']} | 投稿日時: {row['JST_Date'].strftime('%Y-%m-%d %H:%M')}"):
            st.write(row['Text'])
            st.markdown(f"[🔗 X(Twitter)で実際の投稿を見る]({row['URL']})")
    
    st.markdown("---")
    st.subheader("📋 取得データ一覧")
    st.dataframe(df[['JST_Date', 'Engagement', 'Likes', 'Retweets', 'Replies', 'MediaCount', 'Text', 'URL']].sort_values(by='JST_Date', ascending=False))
    
    # CSV Download
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="💾 全データをCSVでダウンロード",
        data=csv,
        file_name=f"{target_user}_analysis.csv",
        mime="text/csv",
    )
