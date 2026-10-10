# Roadmap

1. **Basic agent — implemented, Windows acceptance pending:** local Ollama model
   check, structured controlled actions, Notepad demo, per-action approvals,
   validation and isolated tests. No claim of real desktop acceptance yet.
2. **Reliable Windows interaction — future:** broader application lifecycle,
   improve existing minimal pywinauto integration, window/control inspection,
   layout-independent typing, supported Notepad versions and bounded UIA workers.
3. **Visual awareness — future:** screenshots, UI element identification, state
   verification. Check `/api/show` model capabilities and evaluate a compatible
   local vision model before adding images; Qwen3:4B is not assumed vision-capable.
4. **Multi-step execution — future:** richer planning/history, ambiguity handling,
   bounded recovery, checkpoints and task-completion evaluation. The present loop
   has a small history and stops on failures rather than recovering automatically.
5. **Broader capabilities — future:** carefully scoped file/browser workflows,
   configurable permissions, persistent history and cancel button. Explicit
   approval required for submits, purchases, deletion and account/security changes.
6. **Desktop interface — future:** chat, visible status/history/approvals, model
   and configuration settings. Build after core desktop reliability is validated.
7. **Advanced intelligence — future:** better decomposition, model selection,
   optional local vision/additional models and real-task evaluation benchmarks.

All permanent work belongs in this repository's canonical `main` branch through
an authorized integration. Current session changes are not yet merged into main.
