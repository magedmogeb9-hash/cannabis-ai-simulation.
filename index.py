"""
====================================================================
AI Orchestrator — نظام وكيل ذكاء اصطناعي متعدد المهارات (ملف موحّد)
====================================================================
يحتوي هذا الملف كل طبقات المشروع مدمجة:
CONFIG - SCHEMAS - SKILLS - POLLINATIONS - RESEARCH - CODEGEN -
SANDBOX - GITHUB - AUTH - LOGGER - FASTAPI APP
====================================================================
"""

import os
import sys
import importlib
import importlib.util
import pkgutil
import subprocess
import tempfile
import textwrap
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv()


# ====================================================================
# 1) CONFIG
# ====================================================================
class Settings:
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_REPO_OWNER: str = os.getenv("GITHUB_REPO_OWNER", "")
    GITHUB_REPO_NAME: str = os.getenv("GITHUB_REPO_NAME", "")

    POLLINATIONS_TEXT_URL: str = os.getenv("POLLINATIONS_TEXT_URL", "https://text.pollinations.ai")
    POLLINATIONS_IMAGE_URL: str = os.getenv("POLLINATIONS_IMAGE_URL", "https://image.pollinations.ai/prompt")

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    INTERNAL_API_KEY: str = os.getenv("INTERNAL_API_KEY", "")

    SKILLS_DIR: str = "skills"


settings = Settings()


# ====================================================================
# 2) LOGGER
# ====================================================================
def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


logger = get_logger("orchestrator")


# ====================================================================
# 3) SCHEMAS
# ====================================================================
class SkillResult(BaseModel):
    skill_name: str
    success: bool
    output: Any
    meta: Optional[Dict[str, Any]] = None


class NewSkillRequest(BaseModel):
    skill_name: str
    description: str
    requirements: str


class GithubPushResult(BaseModel):
    branch: str
    file_path: str
    commit_sha: str
    pr_url: Optional[str] = None


# ====================================================================
# 4) BASE SKILL
# ====================================================================
class BaseSkill(ABC):
    """
    كل مهارة (مدمجة أو مولّدة تلقائيًا) ترث من هذا الكلاس وتلتزم بنفس الواجهة
    """
    name: str = "base_skill"
    description: str = "وصف المهارة"

    @abstractmethod
    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


# ====================================================================
# 5) POLLINATIONS CLIENT
# ====================================================================
class PollinationsClient:
    def __init__(self):
        self.text_url = settings.POLLINATIONS_TEXT_URL
        self.image_url = settings.POLLINATIONS_IMAGE_URL

    def generate_text(self, prompt: str, model: str = "openai") -> str:
        response = requests.get(
            f"{self.text_url}/{requests.utils.quote(prompt)}",
            params={"model": model},
            timeout=60,
        )
        response.raise_for_status()
        return response.text

    def generate_image_url(self, prompt: str, width: int = 1024, height: int = 1024) -> str:
        encoded_prompt = requests.utils.quote(prompt)
        return f"{self.image_url}/{encoded_prompt}?width={width}&height={height}"


# ====================================================================
# 6) مهارة مدمجة: توليد نص
# ====================================================================
class TextGenerationSkill(BaseSkill):
    name = "text_generation"
    description = "توليد نص عبر Pollinations AI"

    def __init__(self):
        self.client = PollinationsClient()

    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        prompt = params.get("prompt", "")
        if not prompt:
            return {"success": False, "output": None, "error": "لا يوجد prompt"}
        try:
            text = self.client.generate_text(prompt)
            return {"success": True, "output": text, "error": None}
        except Exception as e:
            return {"success": False, "output": None, "error": str(e)}


# ====================================================================
# 7) مهارة مدمجة: توليد صورة
# ====================================================================
class ImageGenerationSkill(BaseSkill):
    name = "image_generation"
    description = "توليد رابط صورة عبر Pollinations AI"

    def __init__(self):
        self.client = PollinationsClient()

    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        prompt = params.get("prompt", "")
        if not prompt:
            return {"success": False, "output": None, "error": "لا يوجد prompt"}
        width = params.get("width", 1024)
        height = params.get("height", 1024)
        url = self.client.generate_image_url(prompt, width, height)
        return {"success": True, "output": url, "error": None}


# ====================================================================
# 8) SKILL REGISTRY (يحمّل المهارات المدمجة + أي ملفات إضافية في skills/)
# ====================================================================
class SkillRegistry:
    def __init__(self):
        self.skills: Dict[str, BaseSkill] = {}
        self._load_builtin_skills()
        self._load_external_skills()

    def _load_builtin_skills(self):
        for cls in (TextGenerationSkill, ImageGenerationSkill):
            instance = cls()
            self.skills[instance.name] = instance

    def _load_external_skills(self):
        """
        يمسح مجلد skills/ (إن وُجد) لأي ملفات .py إضافية تم إنزالها يدويًا
        من مستودع GitHub بعد قبول Pull Request لمهارة مولّدة
        """
        if not os.path.isdir(settings.SKILLS_DIR):
            return

        for _, module_name, is_pkg in pkgutil.iter_modules([settings.SKILLS_DIR]):
            if is_pkg:
                continue
            try:
                file_path = os.path.join(settings.SKILLS_DIR, f"{module_name}.py")
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, BaseSkill) and attr is not BaseSkill:
                        instance = attr()
                        self.skills[instance.name] = instance
            except Exception as e:
                logger.warning(f"فشل تحميل المهارة الخارجية {module_name}: {e}")

    def get(self, skill_name: str) -> BaseSkill:
        if skill_name not in self.skills:
            raise KeyError(f"المهارة '{skill_name}' غير موجودة")
        return self.skills[skill_name]

    def list_skills(self) -> List[Dict[str, str]]:
        return [{"name": s.name, "description": s.description} for s in self.skills.values()]

    def reload(self):
        self.skills = {}
        self._load_builtin_skills()
        self._load_external_skills()


# ====================================================================
# 9) RESEARCH AGENT
# ====================================================================
class ResearchAgent:
    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return [{"title": "خطأ", "url": "", "snippet": "الرجاء تثبيت duckduckgo-search"}]

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title"),
                    "url": r.get("href"),
                    "snippet": r.get("body"),
                })
        return results

    def summarize(self, results: List[Dict]) -> str:
        return "\n".join(f"- {r['title']}: {r['snippet']}" for r in results)


# ====================================================================
# 10) CODEGEN AGENT (يستخدم Claude لتوليد كود مهارة جديدة)
# ====================================================================
SKILL_TEMPLATE_PROMPT = """
اكتب كود بايثون لمهارة جديدة تلتزم بالضبط بهذا القالب:

from typing import Any, Dict
from index import BaseSkill

class {class_name}(BaseSkill):
    name = "{skill_name}"
    description = "{description}"

    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # اكتب هنا منطق تنفيذ المهارة
        ...

المطلوب من المهارة أن تفعل التالي بالتفصيل:
{requirements}

أعد فقط الكود البرمجي الصالح للتشغيل، بدون أي شرح أو Markdown.
"""


class CodegenAgent:
    def __init__(self):
        import anthropic
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def generate_skill_code(self, skill_name: str, description: str, requirements: str) -> str:
        class_name = "".join(p.capitalize() for p in skill_name.split("_")) + "Skill"
        prompt = SKILL_TEMPLATE_PROMPT.format(
            class_name=class_name, skill_name=skill_name,
            description=description, requirements=requirements,
        )
        message = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        code = message.content[0].text
        return code.replace("```python", "").replace("```", "").strip()


# ====================================================================
# 11) SANDBOX AGENT (يختبر الكود المولّد قبل رفعه)
# ====================================================================
class SandboxAgent:
    def validate_syntax(self, code: str) -> dict:
        try:
            compile(code, "<generated_skill>", "exec")
            return {"valid": True, "error": None}
        except SyntaxError as e:
            return {"valid": False, "error": str(e)}

    def run_isolated_test(self, code: str) -> dict:
        syntax_check = self.validate_syntax(code)
        if not syntax_check["valid"]:
            return {"success": False, "stage": "syntax", "error": syntax_check["error"]}

        # نعرّف BaseSkill مبسّط داخل بيئة الاختبار لتفادي الاعتماد على استيراد index
        test_wrapper = textwrap.dedent(f"""
        from abc import ABC, abstractmethod
        from typing import Any, Dict

        class BaseSkill(ABC):
            name = "base_skill"
            description = "وصف المهارة"
            @abstractmethod
            def run(self, params): raise NotImplementedError

        {code.replace("from index import BaseSkill", "").replace("from typing import Any, Dict", "")}

        import inspect
        for _name, _obj in list(globals().items()):
            if inspect.isclass(_obj) and _name.endswith("Skill") and _name != "BaseSkill":
                try:
                    _instance = _obj()
                    print("SANDBOX_OK:", _instance.name)
                except Exception as _e:
                    print("SANDBOX_INIT_ERROR:", str(_e))
                break
        """)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
            tmp.write(test_wrapper)
            tmp_path = tmp.name

        try:
            result = subprocess.run(["python", tmp_path], capture_output=True, text=True, timeout=15)
            output = result.stdout + result.stderr
            if "SANDBOX_OK" in output:
                return {"success": True, "stage": "execution", "output": output}
            return {"success": False, "stage": "execution", "error": output}
        except subprocess.TimeoutExpired:
            return {"success": False, "stage": "timeout", "error": "تجاوز الكود المهلة الزمنية"}
        finally:
            os.unlink(tmp_path)


# ====================================================================
# 12) GITHUB AGENT (يرفع المهارات المولّدة كـ branch + Pull Request)
# ====================================================================
class GithubAgent:
    def __init__(self):
        from github import Github
        self.gh = Github(settings.GITHUB_TOKEN)
        self.repo = self.gh.get_repo(f"{settings.GITHUB_REPO_OWNER}/{settings.GITHUB_REPO_NAME}")

    def push_new_skill(self, skill_name: str, file_content: str) -> dict:
        base_branch = self.repo.default_branch
        new_branch_name = f"skill/{skill_name}"
        file_path = f"skills/{skill_name}.py"

        base_ref = self.repo.get_git_ref(f"heads/{base_branch}")
        try:
            self.repo.create_git_ref(ref=f"refs/heads/{new_branch_name}", sha=base_ref.object.sha)
        except Exception:
            pass

        try:
            existing_file = self.repo.get_contents(file_path, ref=new_branch_name)
            commit = self.repo.update_file(
                path=file_path, message=f"تحديث مهارة: {skill_name}",
                content=file_content, sha=existing_file.sha, branch=new_branch_name,
            )
        except Exception:
            commit = self.repo.create_file(
                path=file_path, message=f"إضافة مهارة جديدة: {skill_name}",
                content=file_content, branch=new_branch_name,
            )

        pr = self.repo.create_pull(
            title=f"مهارة جديدة: {skill_name}",
            body="تم توليد هذه المهارة تلقائيًا عبر Codegen Agent.",
            head=new_branch_name, base=base_branch,
        )

        return {
            "branch": new_branch_name,
            "file_path": file_path,
            "commit_sha": commit["commit"].sha,
            "pr_url": pr.html_url,
        }


# ====================================================================
# 13) AUTH MIDDLEWARE
# ====================================================================
class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/docs", "/openapi.json", "/redoc", "/health"):
            return await call_next(request)

        if settings.INTERNAL_API_KEY:
            provided_key = request.headers.get("x-api-key", "")
            if provided_key != settings.INTERNAL_API_KEY:
                raise HTTPException(status_code=401, detail="مفتاح API غير صحيح أو مفقود")

        return await call_next(request)


# ====================================================================
# 14) FASTAPI APP
# ====================================================================
app = FastAPI(title="AI Orchestrator", version="1.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(APIKeyMiddleware)

registry = SkillRegistry()
research_agent = ResearchAgent()
sandbox = SandboxAgent()

_codegen: Optional[CodegenAgent] = None
_github_agent: Optional[GithubAgent] = None


def get_codegen() -> CodegenAgent:
    global _codegen
    if _codegen is None:
        _codegen = CodegenAgent()
    return _codegen


def get_github_agent() -> GithubAgent:
    global _github_agent
    if _github_agent is None:
        _github_agent = GithubAgent()
    return _github_agent


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/skills")
def list_skills():
    return registry.list_skills()


@app.post("/run-skill/{skill_name}", response_model=SkillResult)
def run_skill(skill_name: str, params: dict):
    try:
        skill = registry.get(skill_name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    logger.info(f"تنفيذ المهارة: {skill_name}")
    result = skill.run(params)
    return SkillResult(skill_name=skill_name, success=result["success"], output=result["output"])


@app.post("/create-skill")
def create_skill(req: NewSkillRequest):
    logger.info(f"توليد مهارة جديدة: {req.skill_name}")

    code = get_codegen().generate_skill_code(
        skill_name=req.skill_name, description=req.description, requirements=req.requirements,
    )

    test_result = sandbox.run_isolated_test(code)
    if not test_result["success"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "فشل اختبار الكود المولّد، لم يتم رفعه",
                "stage": test_result.get("stage"),
                "error": test_result.get("error"),
            },
        )

    push_result = get_github_agent().push_new_skill(req.skill_name, code)
    logger.info(f"تم رفع المهارة بنجاح: {push_result['pr_url']}")

    return {"status": "success", "sandbox_test": test_result, "github": push_result}


@app.post("/reload-skills")
def reload_skills():
    registry.reload()
    return {"status": "تم إعادة تحميل المهارات", "skills": registry.list_skills()}


@app.post("/research")
def deep_research(query: str):
    results = research_agent.search(query)
    summary = research_agent.summarize(results)
    return {"results": results, "summary": summary}


# ====================================================================
# 15) نقطة التشغيل المباشر
# ====================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("index:app", host="0.0.0.0", port=8000, reload=True)
