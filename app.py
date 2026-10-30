import json
import re
from google import genai
from google.genai import types
import streamlit as st
from prompts import SYSTEM_PROMPT, WELCOME_MESSAGE_PROMPT, SUMMARY_REQUEST_PROMPT
from twilio.rest import Client as TwilioClient


GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
TWILIO_AUTH_TOKEN = st.secrets["TWILIO_AUTH_TOKEN"]
TWILIO_ACCOUNT_SID = st.secrets["TWILIO_ACCOUNT_SID"]
TWILIO_WHATSAPP_FROM = st.secrets["TWILIO_WHATSAPP_FROM"]
TWILIO_CONTENT_SID = st.secrets["TWILIO_CONTENT_SID"]

@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)

@st.cache_resource
def get_twilio_client():
    return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

twilio_client = get_twilio_client()

gemini_client = get_gemini_client()
MODEL_NAME = "gemini-3.8-flash"

def clean_whatsapp_text(text):
    if not text:
        return "No summary available."
    text=" ".join(text.split()) 
    return text[:1500] + "..." if len(text) > 1500 else text

def send_whatsapp(to_number, user_name, summary):
    try:
        digits = re.sub(r"\D", "", str(to_number))
        if digits.startswith("00"):
            digits = digits[2:]
        if not digits:
            raise ValueError("Enter a WhatsApp number with its country code.")

        content_variables=json.dumps(
            {"1":user_name, "2": clean_whatsapp_text(summary)},ensure_ascii=False
        )
        message = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:+{digits}",
            content_sid=TWILIO_CONTENT_SID,
            content_variables=content_variables,
        )
        return True, message.sid
    except Exception as error:
        return False, str(error)

def create_gemini_chat():
    return gemini_client.chats.create(
        model=MODEL_NAME,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
    )

def render_message(message):
    with st.chat_message(message["role"]):
        if message["kind"] == "text":
            st.write(message["content"])
        elif message["kind"] == "image":
            st.image(message["content"])
        


def add_message(role,kind,content):
    st.session_state.message.append({"role": role, "kind": kind, "content": content})
    render_message(st.session_state.message[-1])

def ask_gemini(parts):
    try:
        for chunk in st.session_state.chat.send_message_stream(parts):
            if chunk.text:
                yield chunk.text
    except Exception as error:
        error_text = str(error)
        if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
            yield (
                "Gemini API quota is unavailable for this project right now. "
                "Check the project's active limits in Google AI Studio, or enable billing, "
                "then start a new chat and try again."
            )
        else:
            yield f"Sorry, there was an error generating a response: {error}"


# step1:onboarding (username and phone number)
if 'onboarded' not in st.session_state:
    st.title("🎯 CAREER PARTNER AI")
    st.caption("I'm here to help you balance college, skill development, projects,and internship preparation without overwhelming your schedule.")

    with st.form("onboarding_form"):
        name = st.text_input("Enter your name:")
        whatsapp_number = st.text_input("WhatsApp number with country code",
                                        placeholder="+91xxxxxxxxxx", 
                                        help="This is the number where you can get your career progress summary via WhatsApp.")

        submitted = st.form_submit_button("lets go🚀")    

    if submitted:
        if not name.strip() or not whatsapp_number.strip():
            st.warning("Please fill in both fields.")
        else:
            st.session_state.name = name.strip()
            st.session_state.whatsapp_number = whatsapp_number.strip()
           
           #  step2: create a chat session with the Gemini API

            st.session_state.chat = create_gemini_chat()
            st.session_state.chat_model = MODEL_NAME
            st.session_state.message=[]
            st.session_state.onboarded = True
            st.rerun()  # Rerun the app to reflect the updated state
    st.stop()

# Recreate an existing chat if the configured model changed while this session was open.
if st.session_state.get("chat_model") != MODEL_NAME:
    st.session_state.chat = create_gemini_chat()
    st.session_state.chat_model = MODEL_NAME

# create a chat interface
header_col,button_col = st.columns([0.8, 0.2],vertical_alignment="center")
with header_col:
    st.title("🎯 CAREER PARTNER AI")
with button_col:
    has_user_activity = any(message["role"] == "user" for message in st.session_state.message)
    if st.button("📲 Send to WhatsApp", disabled=not has_user_activity, use_container_width=True):
        with st.spinner("Creating and sending your progress summary..."):
            summary = "".join(ask_gemini([SUMMARY_REQUEST_PROMPT])).strip()
        if summary.startswith(("Gemini API quota is unavailable", "Sorry, there was an error")):
            st.error(summary)
        else:
            success, info = send_whatsapp(
                st.session_state.whatsapp_number,
                st.session_state.name,
                summary,
            )
            if success:
                st.success("✅ Your progress summary was queued for WhatsApp delivery.")
            else:
                st.error(f"Failed to send the WhatsApp summary: {info}")
st.caption(f"logged in as {st.session_state.name} - {st.session_state.whatsapp_number}")
if not st.session_state.message:
    add_message("assistant","text",WELCOME_MESSAGE_PROMPT.format(name=st.session_state.name))
else:
    for message in st.session_state.message:
        render_message(message)

user_input = st.chat_input("Type your message here...",
                           accept_file=True,
                           file_type=["pdf", "docx", "txt", "png", "jpg", "jpeg"]
                           )
if user_input:
    photo = user_input.files[0] if user_input.files else None
    text = user_input.text
    parts = []

    if photo is not None:
        photo_bytes = photo.getvalue()
        add_message("user", "image", photo_bytes)
        parts.append(types.Part.from_bytes(data=photo_bytes, mime_type=photo.type))
    if text:
        add_message("user", "text", text)
        parts.append(text)
    elif photo is not None:
        parts.append("Please provide a description or context for the uploaded file.")
    with st.chat_message("assistant"):
        answer = st.write_stream(ask_gemini(parts))
    st.session_state.message.append(
        {"role": "assistant", "kind": "text", "content": answer}
    )
