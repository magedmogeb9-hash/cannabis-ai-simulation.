# AI Orchestrator — نظام وكيل ذكاء اصطناعي متعدد المهارات

مشروع بملف واحد (`index.py`) يحتوي على:
- وكيل مركزي (Orchestrator) عبر FastAPI
- نظام مهارات قابل للتوسع (Skill Registry) — مهارتان مدمجتان (نص وصورة عبر Pollinations AI)
- وكيل توليد كود (Codegen Agent) عبر Claude API لبناء مهارات جديدة عند الطلب
- بيئة اختبار معزولة (Sandbox Agent) تتحقق من صحة أي كود مولَّد قبل رفعه
- وكيل رفع تلقائي لـ GitHub (Github Agent) — كل مهارة جديدة تُرفع كـ branch + Pull Request
- وكيل بحث عميق (Research Agent)
- حماية بمفتاح API داخلي (Middleware)

## التثبيت

```bash
pip install fastapi uvicorn[standard] pydantic python-dotenv requests PyGithub anthropic duckduckgo-search
