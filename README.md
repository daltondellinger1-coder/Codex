# Codex Mobile (Android)

This project is a native Android app that lets you use Codex from your phone.

## What it does

- Prompts for your OpenAI API key.
- Sends your prompt to the OpenAI Responses API using the `gpt-5-codex` model.
- Shows the returned text in the app.

## Run it on your Android device

1. Install Android Studio (latest stable).
2. Open this folder as a project.
3. Let Gradle sync.
4. Connect your Android phone with USB debugging enabled.
5. Click **Run** in Android Studio and choose your phone.

## Security notes

- The API key currently lives in memory only while app is running.
- Do not share screenshots with your key visible.
- For production, move API calls behind your own backend instead of shipping API keys to clients.

## Next improvements

- Add chat history and multi-turn context.
- Save drafts locally.
- Add markdown rendering for code blocks.
- Add streaming responses for faster feedback.
