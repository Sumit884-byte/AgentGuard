# Demo video

`record_demo.py` records the ~3 minute demo: the real web page, the real
guarded backend (`make_backend`) and live model replies, driven by Playwright,
with narration from macOS `say` and captions burned in.

```bash
pip install playwright && playwright install chromium   # plus ffmpeg on PATH
python demo/record_demo.py                               # writes runs/demo-video/agentguard-demo.mp4
```

What keeps it honest:

- Every reply is live; nothing is scripted except the customer's lines, which
  come from `agentguard/simulator/scenarios.py`.
- The narration after each attack is generated from that attack's receipts,
  so it always describes what actually happened on screen.
- Only idle time while the model is thinking is cut (about 1.5 s of the
  "thinking" state is kept). `scenes.json` next to the video records every
  call, receipt and cut.

Slides for the title, tech stack and closing are in `slides.html`.
