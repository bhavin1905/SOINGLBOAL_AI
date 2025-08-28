import streamlit as st
from soinglobal_smartai.tools.telegram_dex_query_tool import TelegramDexQueryTool
from soinglobal_smartai.tools.enhanced_telegram_dex_tool import EnhancedTelegramDexTool
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

st.set_page_config(page_title="DEX/Telegram Promoters Chatbot", page_icon="🤖")
st.title("🤖 DEX/Telegram Promoters Chatbot")

if 'chat_history' not in st.session_state:
    st.session_state['chat_history'] = []

tool = TelegramDexQueryTool()

with st.form(key='chat_form', clear_on_submit=True):
    user_query = st.text_input("Ask a question about top Telegram promoters or DEX data:")
    submitted = st.form_submit_button("Send")

if submitted and user_query:
    # For demo, use default top_n=3, hours_after_call=24, or parse from query if needed
    response = tool._run(query=user_query, top_n=3, hours_after_call=24)
    st.session_state['chat_history'].append((user_query, response))

# Display chat history
for user_msg, bot_msg in st.session_state['chat_history']:
    st.markdown(f"**You:** {user_msg}")
    st.markdown(f"**Bot:** {bot_msg}")
    
