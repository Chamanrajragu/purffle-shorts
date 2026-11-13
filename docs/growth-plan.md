# PurffleShorts — growth and feature plan (3.0 → desktop launch)

Written 14 Nov 2026, before the Windows / macOS / Linux desktop release on purffle.com.

## Where the app stands

PurffleShorts already does a lot. It turns a topic, a web page, a Reddit post or a long video into finished
vertical videos: an AI-written script that a second pass reviews, free neural voices, stock footage or AI
images or gameplay, word-by-word captions, sound effects, and publishing to YouTube, TikTok, Instagram and
more. It runs on your own computer with cloud AI or free local models (Ollama), and it has a Studio web app,
a command line, a REST API and an MCP server.

What holds back **reach** is not the engine but the first ten minutes and the daily routine:

1. **First run.** A person who double-clicks the desktop app lands on an empty form, with no AI set up.
   Nothing tells them the three ways to start (a free demo, a free local model, a free cloud key).
2. **Making in volume is a terminal feature.** Autopilot (`run`) and batches are CLI-only; the Studio makes
   one video at a time, by hand.
3. **Repeat work.** Every video means setting format, voice, captions, look again. Nothing saves a recipe.
4. **Posting by hand.** Many people post to networks the app can't reach. They need the title, description
   and hashtags ready to copy, and every file in one download.
5. **A desktop app must keep itself current** and look like a real app (icons), and the builds for all
   three systems need to be made the same way every time.
6. **Word of mouth.** Nothing invites a happy user to share the app.

## The plan

Each item ships with tests. [x] = done.

### A. First run and reach
- [x] A1 **Welcome setup** on the Create page when no AI is set up: try a demo with no keys, set up a free
      local model, or paste a free cloud key (Gemini, Groq), with the steps left shown as a checklist.
- [x] A2 **Update check**: the Studio asks GitHub for the newest release once a day (`CHECK_UPDATES=false`
      turns it off) and shows a "new version" link in the sidebar.
- [x] A3 **App icons** for Windows, macOS and Linux made from the logo, and a GitHub Actions workflow that
      builds all three desktop apps on every release.
- [x] A4 **Share the love**: an opt-in "Made with PurffleShorts" line in descriptions (`CREDIT_LINE`), and
      a one-time thank-you with a star/share link after the first finished video.

### B. Make more, faster
- [x] B1 **Batch**: paste many topics, one per line, and queue a video for each.
- [x] B2 **Presets**: save the Create form's settings under a name and apply them in one click.
- [x] B3 **Autopilot in the Studio**: make a video every few hours from the idea queue (planning new ideas
      when it runs dry), publish as Settings say, with a daily cap; on/off from the Queue page.

### C. Library and publishing
- [x] C1 **Post kit**: copy buttons for title, description and hashtags, and one ZIP with the video,
      cover, captions and a text file of the post.
- [x] C2 **Library tools**: sort (newest, best score, most views), filter by format, select several videos
      to publish or delete at once.

### D. Everyday polish
- [x] D1 **Command palette** (Ctrl/⌘ K): jump to any page, video or action by typing.
- [x] D2 **Finished notifications**: a system notification when a video is done (opt-in), and progress in
      the tab title.
- [x] D3 **Your numbers**: videos made, minutes of video and editing hours saved, on the Channel page.

## Later (not in this round)
- Studio interface in the README's languages (Hindi, Spanish, Portuguese, Chinese, Japanese).
- Code signing and notarization (needs the publisher's certificates), and testing the Windows and Linux
  builds on real machines.
- A cover/thumbnail editor, a template gallery shared between users, and team accounts.
