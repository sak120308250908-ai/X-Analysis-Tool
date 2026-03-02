import streamlit as st
import os

# Streamlit Secrets → 環境変数
for _k in ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]:
    if _k in st.secrets:
        os.environ[_k] = str(st.secrets[_k])

import pandas as pd
import re
import io
import zipfile
import matplotlib.pyplot as plt

# japanize-matplotlib の互換処理
try:
    import japanize_matplotlib
except (ImportError, ModuleNotFoundError):
    try:
        import sys, types
        mock_distutils = types.ModuleType("distutils")
        mock_distutils_version = types.ModuleType("distutils.version")
        class LooseVersion:
            def __init__(self, v): self.v = v
            def __lt__(self, o): return False
        mock_distutils_version.LooseVersion = LooseVersion
        mock_distutils.version = mock_distutils_version
        sys.modules["distutils"] = mock_distutils
        sys.modules["distutils.version"] = mock_distutils_version
        import japanize_matplotlib
    except Exception:
        pass

st.set_page_config(page_title="X (Twitter) アカウント分析ツール", layout="wide")

# =====================
# Supabase接続関数
# =====================
def get_connection():
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get("DB_HOST"),
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        sslmode="require"
    )

@st.cache_data(ttl=300)
def get_accounts():
    """取得済みアカウント一覧を取得"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT screen_name FROM tweets ORDER BY screen_name;")
        rows = cur.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        st.error(f"DB接続エラー: {e}")
        return []

@st.cache_data(ttl=300)
def load_tweets(screen_name):
    """指定アカウントのツイートを全件取得"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT tweet_id, created_at, likes, retweets, replies, quotes,
                   media_count, url, full_text
            FROM tweets
            WHERE screen_name = %s
            ORDER BY created_at DESC;
        """, (screen_name,))
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=[
            'tweet_id', 'Date', 'Likes', 'Retweets', 'Replies', 'Quotes',
            'MediaCount', 'URL', 'Text'
        ])
        df['Engagement'] = df['Likes'] + df['Retweets'] * 2 + df['Replies'] * 3
        df['Date'] = pd.to_datetime(df['Date'], utc=True)
        df['JST_Date'] = df['Date'] + pd.Timedelta(hours=9)
        df['Hour'] = df['JST_Date'].dt.hour
        return df
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
        return None

# =====================
# UI
# =====================
st.title("📊 X (Twitter) アカウント分析ツール")
st.write("毎日自動収集したデータを元に、エンゲージメントの傾向を分析します。")

# サイドバー：アカウント選択
st.sidebar.header("📋 アカウント選択")
accounts = get_accounts()

if not accounts:
    st.warning("まだデータが収集されていません。GitHub Actions のバッチを実行してください。")
    st.stop()

selected_account = st.sidebar.selectbox(
    "取得済みアカウント一覧",
    accounts,
    format_func=lambda x: f"@{x}"
)

st.sidebar.markdown("---")
st.sidebar.info("データは毎日AM3時（JST）に自動更新されます。")

# メイン：アカウントIDの手動入力も可能
st.markdown("---")
col_input, col_btn = st.columns([3, 1])
with col_input:
    manual_input = st.text_input(
        "🔍 または直接アカウントIDを入力（@は不要）",
        placeholder="例: elonmusk",
        value=""
    )
with col_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    search_btn = st.button("検索", type="primary")

# 対象アカウント決定
if search_btn and manual_input.strip():
    target_user = manual_input.strip().lstrip("@")
else:
    target_user = selected_account

st.markdown(f"## 📈 @{target_user} のエンゲージメント分析レポート")

# データ読み込み
with st.spinner("データを読み込んでいます..."):
    df = load_tweets(target_user)

if df is None or len(df) == 0:
    st.warning(f"@{target_user} のデータがありません。バッチで収集されていない可能性があります。")
    st.stop()

# =====================
# サマリー
# =====================
col1, col2, col3 = st.columns(3)
col1.metric("取得ツイート数", f"{len(df)}件")
col2.metric("平均エンゲージメントスコア", f"{int(df['Engagement'].mean())}")
col3.metric("最高エンゲージメントスコア", f"{int(df['Engagement'].max())}")

st.markdown("---")

# =====================
# グラフ
# =====================
col_chart1, col_chart2 = st.columns(2)

with col_chart1:
    st.subheader("⏰ 時間帯別の平均エンゲージメント")
    hour_eng = df.groupby('Hour')['Engagement'].mean().reset_index()
    all_hours = pd.DataFrame({'Hour': range(24)})
    hour_eng = pd.merge(all_hours, hour_eng, on='Hour', how='left').fillna(0)
    st.bar_chart(hour_eng.set_index('Hour'))
    st.caption("※棒が高い時間帯に投稿すると伸びやすい傾向があります（日本時間）")

with col_chart2:
    st.subheader("🖼 画像・動画の枚数による差")
    media_eng = df.groupby('MediaCount')['Engagement'].mean().reset_index()
    media_eng_display = media_eng.copy()
    media_eng_display['MediaCount'] = media_eng_display['MediaCount'].astype(str) + "枚"
    st.bar_chart(media_eng_display.set_index('MediaCount'))
    st.caption("※何枚の画像を添付した投稿が一番反響があるかが分かります")

# =====================
# キーワード分析
# =====================
st.markdown("---")
st.subheader("🔑 エンゲージメントが増えやすいキーワードTOP10")
df_kw = None

with st.spinner("キーワードを抽出・分析しています..."):
    try:
        from janome.tokenizer import Tokenizer
        from collections import defaultdict

        t = Tokenizer()
        keyword_eng = defaultdict(list)
        stop_words = {'これ','それ','あれ','この','その','あの','ここ','そこ','あそこ',
                      'ため','こと','もの','よう','わけ','はず','さん','ちゃん','くん',
                      'たち','今日','明日','昨日','今回','みなさん','皆様'}

        for _, row in df.iterrows():
            text = re.sub(r'http\S+|@\S+', '', str(row['Text']))
            tokens = t.tokenize(text)
            words = set()
            for token in tokens:
                pos = token.part_of_speech.split(',')[0]
                word = token.base_form
                if (pos == '名詞' and len(word) > 1
                        and word not in stop_words
                        and re.match(r'^[^\W_]+$', word, re.UNICODE)):
                    words.add(word)
            for w in words:
                keyword_eng[w].append(row['Engagement'])

        kw_stats = [
            {"キーワード": kw, "平均エンゲージメント": int(sum(e)/len(e)), "出現回数": len(e)}
            for kw, e in keyword_eng.items() if len(e) >= 2
        ]

        if kw_stats:
            df_kw = pd.DataFrame(kw_stats).sort_values(
                by="平均エンゲージメント", ascending=False
            ).head(10)
            col_kw1, col_kw2 = st.columns([1, 1.5])
            with col_kw1:
                st.dataframe(df_kw.set_index("キーワード"))
            with col_kw2:
                st.bar_chart(df_kw.set_index("キーワード")["平均エンゲージメント"])
            st.caption("※2回以上使われた名詞から平均スコアが高いTOP10を抽出")
        else:
            st.write("有効なキーワードデータが不足しています。")
    except ImportError:
        st.error("janomeライブラリを準備中です。しばらく後にお試しください。")

# =====================
# 特定キーワード比較
# =====================
st.markdown("---")
st.subheader("🎯 特定キーワードのエンゲージメント比較")
specific_keyword = st.text_input("比較したいキーワードを入力", placeholder="新台")

if specific_keyword:
    df_with = df[df['Text'].str.contains(specific_keyword, case=False, na=False)]
    df_without = df[~df['Text'].str.contains(specific_keyword, case=False, na=False)]

    if len(df_with) == 0:
        st.warning(f"「{specific_keyword}」が含まれるツイートは見つかりませんでした。")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**✅ 「{specific_keyword}」を含む ({len(df_with)}件)**")
            st.metric("平均スコア", f"{int(df_with['Engagement'].mean())}")
            st.metric("平均いいね", f"{int(df_with['Likes'].mean())}")
            st.metric("平均RT", f"{int(df_with['Retweets'].mean())}")
        with c2:
            st.markdown(f"**❌ 含まない ({len(df_without)}件)**")
            if len(df_without) > 0:
                st.metric("平均スコア", f"{int(df_without['Engagement'].mean())}")
                st.metric("平均いいね", f"{int(df_without['Likes'].mean())}")
                st.metric("平均RT", f"{int(df_without['Retweets'].mean())}")

        comp_data = pd.DataFrame({
            "状態": [f"「{specific_keyword}」あり", "なし"],
            "平均スコア": [
                int(df_with['Engagement'].mean()) if len(df_with) > 0 else 0,
                int(df_without['Engagement'].mean()) if len(df_without) > 0 else 0
            ]
        })
        st.bar_chart(comp_data.set_index("状態"))

# =====================
# AI分析
# =====================
st.markdown("---")
st.subheader("🤖 AIによるアカウント総評・分析コメント")

if 'ai_analysis' not in st.session_state:
    st.session_state.ai_analysis = None

api_key = st.text_input("Gemini APIキーを入力してください（無料枠で取得可能です）", type="password")

if st.button("AIに独自の分析を依頼する"):
    if not api_key:
        st.warning("APIキーを入力してください。")
    else:
        with st.spinner("AIが分析中...（約10〜20秒）"):
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                top_tweets = df.sort_values(by='Engagement', ascending=False)
                top_posts_text = "\n".join([
                    f"- いいね:{r['Likes']}, RT:{r['Retweets']}, 本文:{str(r['Text'])[:100]}"
                    for _, r in top_tweets.head(5).iterrows()
                ])
                hour_top = hour_eng.sort_values(by='Engagement', ascending=False).head(3)['Hour'].tolist()
                prompt = f'''
以下はX（Twitter）アカウント「@{target_user}」の投稿データ分析結果です。
プロのSNSマーケターとして「総評」と「エンゲージメントを伸ばすアドバイス」を400文字程度でまとめてください。

【データ概要】
- 取得ツイート数: {len(df)}件
- 平均エンゲージメントスコア: {int(df['Engagement'].mean())}

【バズりやすい時間帯トップ3】
{hour_top}時台

【反響が大きかったトップ5の投稿内容】
{top_posts_text}

「このアカウント特有の強み・特徴」と「具体的な今後のアクション」を論理的に出力してください。
'''
                response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                st.info(response.text)
                st.session_state.ai_analysis = response.text
            except Exception as e:
                st.error(f"AI分析中にエラーが発生しました: {e}")

# =====================
# TOP5投稿
# =====================
st.markdown("---")
st.subheader("🔥 エンゲージメントTOP 5 投稿")
top_tweets = df.sort_values(by='Engagement', ascending=False).head(5)
for _, row in top_tweets.iterrows():
    with st.expander(
        f"👑 スコア: {int(row['Engagement'])} | いいね: {row['Likes']} | RT: {row['Retweets']} | "
        f"投稿日時: {row['JST_Date'].strftime('%Y-%m-%d %H:%M')}"
    ):
        st.write(row['Text'])
        st.markdown(f"[🔗 X(Twitter)で実際の投稿を見る]({row['URL']})")

# =====================
# データ一覧 & ダウンロード
# =====================
st.markdown("---")
st.subheader("📋 取得データ一覧")
st.dataframe(
    df[['JST_Date', 'Engagement', 'Likes', 'Retweets', 'Replies', 'MediaCount', 'Text', 'URL']]
    .sort_values(by='JST_Date', ascending=False)
)

csv = df.to_csv(index=False).encode('utf-8-sig')
st.download_button(
    label="💾 全データをCSVでダウンロード",
    data=csv,
    file_name=f"{target_user}_analysis.csv",
    mime="text/csv",
)

# =====================
# ZIPダウンロード（AI分析完了後）
# =====================
if st.session_state.ai_analysis:
    st.markdown("---")
    st.subheader("🎯 提案用レポート・ダウンロード")

    def fig_to_bytes(fig):
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches='tight')
        plt.close(fig)
        return buf.getvalue()

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zf:
        zf.writestr("0_AI分析レポート.txt", st.session_state.ai_analysis)
        zf.writestr("1_全ツイートデータ.csv", df.to_csv(index=False).encode('utf-8-sig'))

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar(hour_eng['Hour'], hour_eng['Engagement'], color='skyblue')
        ax.set_title(f"@{target_user} 時間帯別の平均エンゲージメント")
        ax.set_xlabel("時間（24時間表記）")
        ax.set_ylabel("平均スコア")
        ax.set_xticks(range(24))
        zf.writestr("2_時間帯別分析グラフ.png", fig_to_bytes(fig))

        if df_kw is not None:
            zf.writestr("3_キーワード分析データ.csv", df_kw.to_csv(index=False).encode('utf-8-sig'))
            fig, ax = plt.subplots(figsize=(12, 6))
            ax.bar(df_kw['キーワード'], df_kw['平均エンゲージメント'], color='orange')
            ax.set_title(f"@{target_user} エンゲージメントが高いキーワードTOP10")
            ax.set_ylabel("平均スコア")
            plt.xticks(rotation=45)
            zf.writestr("3_キーワード分析グラフ.png", fig_to_bytes(fig))

    st.download_button(
        label="🎁 提案用フルセットをまとめてダウンロード (.zip)",
        data=zip_buffer.getvalue(),
        file_name=f"{target_user}_full_report.zip",
        mime="application/zip",
    )
