import os, time, uuid, asyncio, aiohttp, secrets
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="9tu Video Proxy")

# 请求体大小限制（默认 50MB，防止 OOM）
MAX_BODY_SIZE = int(os.getenv("MAX_BODY_SIZE_MB", "50")) * 1024 * 1024


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    content_length = request.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_BODY_SIZE:
        return JSONResponse(
            status_code=413,
            content={"error": {"message": f"Request body too large, max {MAX_BODY_SIZE // 1024 // 1024}MB", "code": "413"}},
        )
    return await call_next(request)

# --- 9tu API 配置 ---
raw_token = os.getenv("9TU_AUTH_TOKEN", "Bearer YOUR_TOKEN")
AUTH_TOKEN = raw_token if raw_token.startswith("Bearer ") else "Bearer " + raw_token
API_BASE_URL = os.getenv("9TU_API_BASE_URL", "https://your-api-domain.com")
tasks_store = {}

DEFAULT_MODEL_ID = os.getenv("9TU_MODEL_ID", "22")
DEFAULT_GROUP_ID = os.getenv("9TU_GROUP_ID", "14")
DEFAULT_DURATION = int(os.getenv("9TU_DURATION", "5"))
DEFAULT_RESOLUTION = os.getenv("9TU_RESOLUTION", "720p")
DEFAULT_ASPECT_RATIO = os.getenv("9TU_ASPECT_RATIO", "16:9")
POLL_INTERVAL = int(os.getenv("9TU_POLL_INTERVAL", "5"))
MAX_POLL_TIME = int(os.getenv("9TU_MAX_POLL_TIME", "600"))

# --- 管理后台配置 ---
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
CONFIG_DIR = os.getenv("CONFIG_DIR", "/config")
ENV_FILE = os.path.join(CONFIG_DIR, ".env")
SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT", "3600"))  # 管理后台 session 过期时间（秒）

# 支持运行时修改密码（从 .env 重新加载）
def _reload_admin_password():
    global ADMIN_PASSWORD
    env_file = os.path.join(CONFIG_DIR, ".env")
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ADMIN_PASSWORD="):
                    ADMIN_PASSWORD = line.split("=", 1)[1]
                    return


def _load_all_config_from_file():
    """容器启动时从 /config/.env 加载所有配置，覆盖 Docker env_file 的初始值。
    
    解决 web 管理后台写入 /config/.env 后重启容器不生效的问题：
    docker-compose 的 env_file 加载的是 compose 目录的 .env，
    而 web 写入的是挂载卷 /config/.env，两者不是同一个文件。
    """
    global raw_token, AUTH_TOKEN, API_BASE_URL
    global DEFAULT_MODEL_ID, DEFAULT_GROUP_ID, DEFAULT_DURATION
    global DEFAULT_RESOLUTION, DEFAULT_ASPECT_RATIO
    global POLL_INTERVAL, MAX_POLL_TIME, ADMIN_PASSWORD

    env_file = os.path.join(CONFIG_DIR, ".env")
    if not os.path.exists(env_file):
        return

    config = {}
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()

    if "9TU_AUTH_TOKEN" in config and config["9TU_AUTH_TOKEN"].strip():
        raw_token = config["9TU_AUTH_TOKEN"]
        AUTH_TOKEN = raw_token if raw_token.startswith("Bearer ") else "Bearer " + raw_token
    if "9TU_API_BASE_URL" in config and config["9TU_API_BASE_URL"].strip():
        API_BASE_URL = config["9TU_API_BASE_URL"]
    if "9TU_MODEL_ID" in config and config["9TU_MODEL_ID"].strip():
        DEFAULT_MODEL_ID = config["9TU_MODEL_ID"]
    if "9TU_GROUP_ID" in config and config["9TU_GROUP_ID"].strip():
        DEFAULT_GROUP_ID = config["9TU_GROUP_ID"]
    if "9TU_DURATION" in config and config["9TU_DURATION"].strip():
        DEFAULT_DURATION = int(config["9TU_DURATION"])
    if "9TU_RESOLUTION" in config and config["9TU_RESOLUTION"].strip():
        DEFAULT_RESOLUTION = config["9TU_RESOLUTION"]
    if "9TU_ASPECT_RATIO" in config and config["9TU_ASPECT_RATIO"].strip():
        DEFAULT_ASPECT_RATIO = config["9TU_ASPECT_RATIO"]
    if "9TU_POLL_INTERVAL" in config and config["9TU_POLL_INTERVAL"].strip():
        POLL_INTERVAL = int(config["9TU_POLL_INTERVAL"])
    if "9TU_MAX_POLL_TIME" in config and config["9TU_MAX_POLL_TIME"].strip():
        MAX_POLL_TIME = int(config["9TU_MAX_POLL_TIME"])
    if "ADMIN_PASSWORD" in config and config["ADMIN_PASSWORD"].strip():
        ADMIN_PASSWORD = config["ADMIN_PASSWORD"]


@app.on_event("startup")
async def startup_event():
    _load_all_config_from_file()

# --- 会话管理 ---
_sessions = {}
ADMIN_TOKEN_PREFIX = "adm_"


def _gen_token():
    return ADMIN_TOKEN_PREFIX + secrets.token_hex(16)


def _check_session(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        if token in _sessions:
            created = _sessions[token]
            if time.time() - created < SESSION_TIMEOUT:
                return token
            del _sessions[token]
    raise HTTPException(status_code=401, detail="未登录")


def _read_env_file():
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def _write_env_file(env: dict):
    with open(ENV_FILE, "w") as f:
        f.write("# 9tu Proxy 配置\n# 编辑后点击「重启代理」生效\n\n")
        for k, v in env.items():
            f.write(f"{k}={v}\n")


def _get_config():
    env = _read_env_file()
    return {
        "9TU_API_BASE_URL": env.get("9TU_API_BASE_URL", API_BASE_URL),
        "9TU_AUTH_TOKEN": env.get("9TU_AUTH_TOKEN", raw_token),
        "9TU_MODEL_ID": env.get("9TU_MODEL_ID", DEFAULT_MODEL_ID),
        "9TU_GROUP_ID": env.get("9TU_GROUP_ID", DEFAULT_GROUP_ID),
        "9TU_DURATION": env.get("9TU_DURATION", str(DEFAULT_DURATION)),
        "9TU_RESOLUTION": env.get("9TU_RESOLUTION", DEFAULT_RESOLUTION),
        "9TU_ASPECT_RATIO": env.get("9TU_ASPECT_RATIO", DEFAULT_ASPECT_RATIO),
        "9TU_POLL_INTERVAL": env.get("9TU_POLL_INTERVAL", str(POLL_INTERVAL)),
        "9TU_MAX_POLL_TIME": env.get("9TU_MAX_POLL_TIME", str(MAX_POLL_TIME)),
    }

# ========== 9tu API 功能 ==========

class VideoGenerationRequest(BaseModel):
    model: Optional[str] = "9tu-video"
    prompt: str = ""
    image: Optional[str] = None
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    n: Optional[int] = 1
    metadata: Optional[dict] = None
    images: Optional[list] = None
    videos: Optional[list] = None
    audioUrls: Optional[list] = None
    first_frame: Optional[str] = None
    last_frame: Optional[str] = None


async def create_9tu_task(prompt, files=None, options=None):
    if files is None: files = {}
    if options is None: options = {}
    payload = {
        "model_id": options.get("model_id", DEFAULT_MODEL_ID),
        "group_id": options.get("group_id", DEFAULT_GROUP_ID),
        "prompt": prompt,
        "images": files.get("images", []),
        "values": {
            "mode": options.get("mode", "references"),
            "aspect_ratio": options.get("aspect_ratio", DEFAULT_ASPECT_RATIO),
            "duration": options.get("duration", DEFAULT_DURATION),
            "resolution": options.get("resolution", DEFAULT_RESOLUTION),
        }
    }
    if files.get("videos"): payload["values"]["videos"] = files["videos"]
    if files.get("audioUrls"): payload["values"]["audioUrls"] = files["audioUrls"]
    if files.get("first_frame"): payload["values"]["first_frame"] = files["first_frame"]
    if files.get("last_frame"): payload["values"]["last_frame"] = files["last_frame"]
    headers = {"Authorization": AUTH_TOKEN, "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{API_BASE_URL}/api/tasks", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
            d = await r.json()
            if d.get("code") == 0: return d["data"]
            raise Exception(f"9tu API error: {d.get('message', 'unknown')}")


async def query_9tu_task(task_no):
    headers = {"Authorization": AUTH_TOKEN, "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{API_BASE_URL}/api/tasks/{task_no}", headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
            d = await r.json()
            if d.get("code") == 0: return d["data"]
            raise Exception(f"9tu query error: {d.get('message', 'unknown')}")


async def poll_9tu_task(task_no):
    start = time.time()
    while True:
        if time.time() - start > MAX_POLL_TIME:
            raise Exception("task polling timeout")
        try:
            td = await query_9tu_task(task_no)
            s = td.get("status", "")
            if s in ("completed", "success"):
                return {"status": "completed", "result_url": td.get("result_url", ""), "video_url": td.get("result_url", "")}
            if s in ("failed", "error", "cancelled"):
                raise Exception(f"task ended with status: {s}")
            await asyncio.sleep(POLL_INTERVAL)
        except Exception as e:
            if "task ended with status" in str(e): raise
            await asyncio.sleep(POLL_INTERVAL)


async def handle_video_generation(body):
    files = {"images": [], "videos": [], "audioUrls": []}
    for k in ("image", "images", "videos", "audioUrls"):
        v = body.get(k)
        if v:
            if isinstance(v, list):
                files[k if k != "image" else "images"].extend(v)
            else:
                files[k if k != "image" else "images"].append(v)
    for k in ("first_frame", "last_frame"):
        if body.get(k):
            files[k] = body[k]
    opts = {}
    if body.get("metadata"):
        opts.update(body["metadata"])
    if body.get("duration"):
        opts["duration"] = int(body["duration"])
    if "duration" not in opts:
        opts["duration"] = DEFAULT_DURATION
    w, h = body.get("width"), body.get("height")
    if w and h:
        opts["aspect_ratio"] = f"{w}:{h}"
    model = body.get("model", "9tu-video")
    prompt = body.get("prompt", "generate video")
    task = await create_9tu_task(prompt, files, opts)
    task_no = task.get("task_no", str(uuid.uuid4()))
    iid = str(uuid.uuid4())
    created_at = int(time.time())
    size_str = f"{w}x{h}" if w and h else "1920x1080"
    tasks_store[iid] = {
        "task_no": task_no,
        "status": "queued",
        "created_at": created_at,
        "model": model,
        "size": size_str,
        "seconds": str(opts.get("duration", DEFAULT_DURATION)),
    }
    asyncio.create_task(_bp(iid, task_no))
    return {
        "id": iid,
        "status": "queued",
        "model": model,
        "progress": 0,
        "created_at": created_at,
        "seconds": str(opts.get("duration", DEFAULT_DURATION)),
        "size": size_str,
        "error": None,
    }


async def _bp(iid, task_no):
    try:
        r = await poll_9tu_task(task_no)
        tasks_store[iid].update(r)
        tasks_store[iid]["status"] = r["status"]
    except Exception as e:
        tasks_store[iid]["status"] = "failed"
        tasks_store[iid]["error"] = str(e)


@app.post("/v1/video/generations")
@app.post("/v1/videos")
async def create_video(req: VideoGenerationRequest):
    return await handle_video_generation(req.model_dump())


@app.get("/v1/video/generations/{task_id}")
@app.get("/v1/videos/{task_id}")
async def get_video(task_id: str):
    t = tasks_store.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    status = t.get("status", "unknown")
    progress_map = {"queued": 0, "processing": 50, "in_progress": 50, "completed": 100, "success": 100, "failed": 0}
    err = t.get("error")
    return {
        "id": task_id,
        "status": status,
        "model": t.get("model", "9tu-video"),
        "progress": progress_map.get(status, 0),
        "created_at": t.get("created_at", 0),
        "seconds": t.get("seconds", str(DEFAULT_DURATION)),
        "size": t.get("size", "1920x1080"),
        "result_url": t.get("result_url"),
        "video_url": t.get("video_url"),
        "error": {"message": err, "code": status} if err else None,
    }


@app.get("/v1/videos/{task_id}/content")
async def get_video_content(task_id: str):
    t = tasks_store.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    status = t.get("status", "")
    if status not in ("completed", "success"):
        raise HTTPException(status_code=400, detail="Video not ready")
    video_url = t.get("result_url") or t.get("video_url")
    if not video_url:
        raise HTTPException(status_code=404, detail="Video URL not found")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(video_url, timeout=aiohttp.ClientTimeout(total=120)) as r:
                if r.status != 200:
                    raise HTTPException(status_code=502, detail="Upstream video fetch failed")
                content_type = r.headers.get("Content-Type", "video/mp4")
                content_length = r.headers.get("Content-Length")
                headers = {"Content-Type": content_type}
                if content_length:
                    headers["Content-Length"] = content_length
                return StreamingResponse(
                    r.content.iter_chunked(1024 * 64),
                    status_code=200,
                    headers=headers,
                )
    except aiohttp.ClientError:
        raise HTTPException(status_code=502, detail="Upstream video fetch failed")


@app.get("/health")
async def health():
    return {"status": "ok"}


# ========== 管理后台 API ==========

@app.post("/admin/api/login")
async def admin_login(data: dict):
    if data.get("password") != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="密码错误")
    token = _gen_token()
    _sessions[token] = time.time()
    return {"token": token}


@app.get("/admin/api/config", dependencies=[Depends(_check_session)])
async def get_config():
    return _get_config()


@app.post("/admin/api/config", dependencies=[Depends(_check_session)])
async def save_config(data: dict):
    allowed_keys = {
        "ADMIN_PASSWORD", "9TU_API_BASE_URL", "9TU_AUTH_TOKEN", "9TU_MODEL_ID", "9TU_GROUP_ID",
        "9TU_DURATION", "9TU_RESOLUTION", "9TU_ASPECT_RATIO",
        "9TU_POLL_INTERVAL", "9TU_MAX_POLL_TIME",
    }
    env = {}
    for k in allowed_keys:
        if k in data:
            env[k] = str(data[k]).strip()
    _write_env_file(env)
    return {"status": "ok", "message": "配置已保存，点击重启生效"}


@app.post("/admin/api/restart", dependencies=[Depends(_check_session)])
async def admin_restart():
    import asyncio as _asyncio
    _asyncio.create_task(_delayed_exit())
    return {"status": "ok", "message": "重启中（约 3 秒后服务恢复）"}


async def _delayed_exit():
    await asyncio.sleep(1)
    os._exit(0)


# ========== 管理后台页面 ==========

ADMIN_HTML = """<!DOCTYPE html><html lang=zh><head><meta charset=UTF-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>9tu Proxy 管理</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
body{background:#f5f6fa;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:#fff;border-radius:12px;box-shadow:0 2px 20px rgba(0,0,0,.08);width:100%;max-width:560px;padding:32px}
h2{font-size:22px;font-weight:600;margin-bottom:24px;color:#1a1a2e}
.form-group{margin-bottom:16px}
label{display:block;font-size:13px;font-weight:500;color:#555;margin-bottom:4px}
input{width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:8px;font-size:14px;outline:none;transition:.2s}
input:focus{border-color:#4a6cf7;box-shadow:0 0 0 3px rgba(74,108,247,.12)}
.btn{width:100%;padding:12px;border:none;border-radius:8px;font-size:15px;font-weight:500;cursor:pointer;transition:.2s}
.btn-primary{background:#4a6cf7;color:#fff}
.btn-primary:hover{background:#3b5de7}
.btn-danger{background:#e74c3c;color:#fff}
.btn-danger:hover{background:#c0392b}
.btn-success{background:#27ae60;color:#fff}
.btn-success:hover{background:#219a52}
.btn-outline{background:transparent;border:1px solid #ddd;color:#555}
.btn-outline:hover{background:#f5f5f5}
.toast{position:fixed;top:20px;left:50%;transform:translateX(-50%);padding:12px 24px;border-radius:8px;color:#fff;font-size:14px;z-index:100;display:none;animation:fadeIn .3s}
.toast.success{background:#27ae60}
.toast.error{background:#e74c3c}
@keyframes fadeIn{from{opacity:0;transform:translateX(-50%) translateY(-10px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}
.hidden{display:none!important}
.section-title{font-size:14px;font-weight:600;color:#1a1a2e;margin:20px 0 12px;padding-bottom:8px;border-bottom:1px solid #eee}
.row{display:flex;gap:12px}
.row>.form-group{flex:1}
.actions{display:flex;gap:12px;margin-top:20px}
.actions .btn{flex:1}
.status-badge{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:500}
.status-badge.ok{background:#e8f5e9;color:#27ae60}
.status-badge.err{background:#fde8e8;color:#e74c3c}
</style></head><body>
<div id=toast class=toast></div>
<div id=login class=card>
<h2>🔐 管理登录</h2>
<div class=form-group><label>管理密码</label><input type=password id=loginPwd placeholder=输入管理密码></div>
<button class="btn btn-primary" onclick=login()>登录</button>
</div>
<div id=dashboard class="card hidden">
<h2>⚙️ 9tu Proxy 配置</h2>
<div id=fields></div>
<div class=actions>
<button class="btn btn-success" onclick=saveConfig()>💾 保存</button>
<button class="btn btn-danger" onclick=doRestart()>🔄 重启代理</button>
</div>
</div>
<script>
let token='';const fields=[
{key:'9TU_API_BASE_URL',label:'API 地址',type:'text'},
{key:'9TU_AUTH_TOKEN',label:'认证 Token',type:'password'},
{key:'9TU_MODEL_ID',label:'模型 ID',type:'text'},
{key:'9TU_GROUP_ID',label:'分组 ID',type:'text'},
{key:'9TU_DURATION',label:'视频时长(秒)',type:'text'},
{key:'9TU_RESOLUTION',label:'分辨率',type:'text'},
{key:'9TU_ASPECT_RATIO',label:'画面比例',type:'text'},
{key:'9TU_POLL_INTERVAL',label:'轮询间隔(秒)',type:'text'},
{key:'9TU_MAX_POLL_TIME',label:'超时时间(秒)',type:'text'},
{key:'ADMIN_PASSWORD',label:'管理密码',type:'password'},
];
function toast(msg,type){const t=document.getElementById('toast');t.textContent=msg;t.className='toast '+type;t.style.display='block';setTimeout(()=>t.style.display='none',3000)}
function show(id){document.getElementById('login').classList.toggle('hidden',id!=='login');document.getElementById('dashboard').classList.toggle('hidden',id!=='dashboard')}
async function login(){const pwd=document.getElementById('loginPwd').value;if(!pwd)return toast('请输入密码','error');try{const r=await fetch('/admin/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pwd})});const d=await r.json();if(!r.ok)return toast(d.detail||'登录失败','error');token=d.token;show('dashboard');loadConfig()}catch(e){toast('网络错误','error')}}
async function loadConfig(){try{const r=await fetch('/admin/api/config',{headers:{'Authorization':'Bearer '+token}});const d=await r.json();if(!r.ok)return toast(d.detail||'加载失败','error');renderFields(d)}catch(e){toast('加载失败','error')}}
function renderFields(config){let html='';fields.forEach(f=>{html+='<div class=form-group><label>'+f.label+'</label><input type='+f.type+' id='+f.key+' value="'+(config[f.key]||'')+'" placeholder="输入'+f.label+'"></div>'});document.getElementById('fields').innerHTML=html}
async function saveConfig(){const data={};fields.forEach(f=>data[f.key]=document.getElementById(f.key).value);try{const r=await fetch('/admin/api/config',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify(data)});const d=await r.json();if(!r.ok)return toast(d.detail||'保存失败','error');toast(d.message,'success')}catch(e){toast('保存失败','error')}}
async function doRestart(){if(!confirm('确定要重启代理吗？服务会短暂中断（约3秒）。'))return;try{const r=await fetch('/admin/api/restart',{method:'POST',headers:{'Authorization':'Bearer '+token}});const d=await r.json();if(!r.ok)return toast(d.detail||'重启失败','error');toast(d.message,'success');setTimeout(()=>{window.location.reload()},4000)}catch(e){toast('重启失败','error')}}
</script></body></html>"""


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/", response_class=HTMLResponse)
async def admin_page():
    return ADMIN_HTML


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PROXY_PORT", "8001")))
