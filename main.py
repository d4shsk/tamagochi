from fastapi import FastAPI, Depends, HTTPException, status, Request, Form
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
import random

from database import get_db, init_db, User, Team, TeamMember, Mission, UserAction, PetStage

app = FastAPI(title="SlowDown")

templates = Jinja2Templates(directory="templates")
app.mount("/imgs", StaticFiles(directory="imgs"), name="imgs")

# Security
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        user = db.query(User).filter(User.username == username).first()
        return user
    except JWTError:
        return None

def get_stage_name(stage: PetStage) -> str:
    names = {
        PetStage.EGG: "Яйцо",
        PetStage.BABY: "Малыш",
        PetStage.TEEN: "Подросток",
        PetStage.ADULT: "Взрослый"
    }
    return names.get(stage, "Неизвестно")

def check_evolution(team: Team):
    """Check if pet should evolve based on progress"""
    if team.progress >= 100 and team.pet_stage == PetStage.EGG:
        team.pet_stage = PetStage.BABY
        team.progress = 0
    elif team.progress >= 100 and team.pet_stage == PetStage.BABY:
        team.pet_stage = PetStage.TEEN
        team.progress = 0
    elif team.progress >= 100 and team.pet_stage == PetStage.TEEN:
        team.pet_stage = PetStage.ADULT
        team.progress = 0
    return team

def apply_time_decay(db: Session, team: Team):
    if team.is_dead:
        return
        
    now = datetime.utcnow()
    delta_minutes = (now - team.last_updated).total_seconds() / 60
    amount = int(delta_minutes / 10)  # 1 point every 10 minutes
    
    if amount > 0:
        # Decay stats
        team.hunger = max(0, team.hunger - amount)
        team.energy = max(0, team.energy - amount)
        team.mood = max(0, team.mood - amount)
        
        # Passive Growth
        # Only grow if stats are above 0
        if team.hunger > 0 and team.energy > 0 and team.mood > 0:
            today = now.date()
            mission = db.query(Mission).filter(
                Mission.team_id == team.id,
                Mission.date >= datetime.combine(today, datetime.min.time())
            ).first()
            
            # Rate: 1 progress point per minute normally, or 3 if mission is completed
            passive_rate = 3 if (mission and mission.completed) else 1
            minutes_passed = amount * 10
            team.progress = min(100, team.progress + (minutes_passed * passive_rate))
            
        # Add exactly the processed time to keep the remainder
        team.last_updated += timedelta(minutes=amount * 10)
        db.commit()

def create_daily_mission(db: Session, team: Team):
    """Create a daily mission for the team"""
    action_types = [
        ("feed", "Покормить Серунчика", 5),
        ("play", "Поиграть с Серунчиком", 5),
        ("rest", "Дать Серунчику отдохнуть", 3)
    ]
    action_type, description, target = random.choice(action_types)
    
    mission = Mission(
        team_id=team.id,
        description=description,
        target_count=target,
        action_type=action_type
    )
    db.add(mission)
    db.commit()
    return mission

@app.on_event("startup")
async def startup():
    init_db()

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=302)
        
    error = request.query_params.get("error")
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error
    })

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == username).first():
        return HTMLResponse(content="<h1>Пользователь уже существует</h1><a href='/register'>Назад</a>", status_code=400)
    
    hashed_password = get_password_hash(password)
    user = User(username=username, password_hash=hashed_password)
    db.add(user)
    db.commit()
    
    return RedirectResponse(url="/", status_code=302)

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        return RedirectResponse(url="/?error=1", status_code=302)
    
    access_token = create_access_token(data={"sub": user.username})
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/", status_code=302)
    
    team_member = db.query(TeamMember).filter(TeamMember.user_id == current_user.id).first()
    
    if not team_member:
        return templates.TemplateResponse("create_pet.html", {
            "request": request,
            "current_user": current_user
        })
    
    team = team_member.team
    
    # Recharge AP logic (1 per hour)
    now = datetime.utcnow()
    if team_member.action_points >= 5:
        team_member.last_ap_reset = now
        db.commit()
    else:
        hours_passed = int((now - team_member.last_ap_reset).total_seconds() / 3600)
        if hours_passed > 0:
            team_member.action_points = min(5, team_member.action_points + hours_passed)
            team_member.last_ap_reset += timedelta(hours=hours_passed)
            db.commit()
    
    apply_time_decay(db, team)
    
    members = db.query(TeamMember).filter(TeamMember.team_id == team.id).all()
    member_users = [db.query(User).filter(User.id == m.user_id).first() for m in members]
    
    actions = db.query(UserAction).filter(UserAction.team_id == team.id).order_by(UserAction.performed_at.desc()).limit(10).all()
    action_details = []
    for action in actions:
        user = db.query(User).filter(User.id == action.user_id).first()
        action_name = {"feed": "Покормил", "play": "Поиграл", "rest": "Дал отдохнуть"}.get(action.action_type, action.action_type)
        action_details.append({
            "username": user.username if user else "Неизвестно",
            "action": action_name,
            "time": action.performed_at.strftime("%H:%M")
        })
    
    # Get or create daily mission
    today = datetime.utcnow().date()
    mission = db.query(Mission).filter(
        Mission.team_id == team.id,
        Mission.date >= datetime.combine(today, datetime.min.time())
    ).first()
    
    if not mission:
        mission = create_daily_mission(db, team)
    
    stage_name = get_stage_name(team.pet_stage)
    
    error_msg = request.query_params.get("error")
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "current_user": current_user,
        "team": team,
        "stage_name": stage_name,
        "members": [(m, u) for m, u in zip(members, member_users)],
        "actions": action_details,
        "mission": mission,
        "member_count": len(members),
        "action_points": team_member.action_points,
        "error_msg": error_msg
    })

@app.post("/create-pet")
async def create_pet(pet_type: str = Form("rooster"), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/", status_code=302)
    
    # Check if user already has a team
    existing = db.query(TeamMember).filter(TeamMember.user_id == current_user.id).first()
    if existing:
        return RedirectResponse(url="/dashboard", status_code=302)
    
    team = Team(pet_type=pet_type, last_updated=datetime.utcnow())
    db.add(team)
    db.commit()
    db.refresh(team)
    
    member = TeamMember(user_id=current_user.id, team_id=team.id, is_owner=True)
    db.add(member)
    db.commit()
    
    # Create first mission
    create_daily_mission(db, team)
    
    return RedirectResponse(url="/dashboard", status_code=302)

@app.post("/invite")
async def invite(code: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/", status_code=302)
    
    team_member = db.query(TeamMember).filter(TeamMember.user_id == current_user.id).first()
    if not team_member:
        return RedirectResponse(url="/dashboard", status_code=302)
    
    team = team_member.team
    current_count = db.query(TeamMember).filter(TeamMember.team_id == team.id).count()
    
    if current_count >= 4:
        return HTMLResponse(content="<h1>Команда уже полная (максимум 4 человека)</h1><a href='/dashboard'>Назад</a>", status_code=400)
    
    # Find user by username
    invited_user = db.query(User).filter(User.username == code).first()
    if not invited_user:
        return HTMLResponse(content="<h1>Пользователь не найден</h1><a href='/dashboard'>Назад</a>", status_code=404)
    
    # Check if user already has a team
    invited_existing = db.query(TeamMember).filter(TeamMember.user_id == invited_user.id).first()
    if invited_existing:
        if invited_existing.team_id == team.id:
            return HTMLResponse(content="<h1>Пользователь уже в вашей команде</h1><a href='/dashboard'>Назад</a>", status_code=400)
        else:
            return HTMLResponse(content="<h1>У этого пользователя уже есть питомец. Чтобы присоединиться, ему нужно сначала с ним попрощаться (кремировать).</h1><a href='/dashboard'>Назад</a>", status_code=400)
    
    new_member = TeamMember(user_id=invited_user.id, team_id=team.id)
    db.add(new_member)
    db.commit()
    
    return RedirectResponse(url="/dashboard", status_code=302)

@app.post("/action/cremate")
async def cremate(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/", status_code=302)
    team_member = db.query(TeamMember).filter(TeamMember.user_id == current_user.id).first()
    if not team_member:
        return RedirectResponse(url="/dashboard", status_code=302)
        
    team = team_member.team
    
    db.query(Mission).filter(Mission.team_id == team.id).delete()
    db.query(UserAction).filter(UserAction.team_id == team.id).delete()
    db.query(TeamMember).filter(TeamMember.team_id == team.id).delete()
    db.query(Team).filter(Team.id == team.id).delete()
    db.commit()
    
    return RedirectResponse(url="/dashboard", status_code=302)

@app.post("/action/resuscitate")
async def resuscitate(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/", status_code=302)
    team_member = db.query(TeamMember).filter(TeamMember.user_id == current_user.id).first()
    if not team_member:
        return RedirectResponse(url="/dashboard", status_code=302)
        
    team = team_member.team
    
    if team.is_dead:
        return RedirectResponse(url="/dashboard", status_code=302)
        
    if team.resuscitation_count == 0:
        success = True
    else:
        success = random.choice([True, False])
        
    team.resuscitation_count += 1
    team.last_updated = datetime.utcnow()
    
    if success:
        team.hunger = 50
        team.energy = 50
        team.mood = 50
    else:
        team.is_dead = True
        
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=302)

@app.post("/action/{action_type}")
async def perform_action(action_type: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/", status_code=302)
    
    team_member = db.query(TeamMember).filter(TeamMember.user_id == current_user.id).first()
    if not team_member:
        return RedirectResponse(url="/dashboard", status_code=302)
    
    team = team_member.team
    
    if team.is_dead or team.hunger <= 0:
        return RedirectResponse(url="/dashboard", status_code=302)
        
    # Recharge AP logic
    now = datetime.utcnow()
    if team_member.action_points >= 5:
        team_member.last_ap_reset = now
        db.commit()
    else:
        hours_passed = int((now - team_member.last_ap_reset).total_seconds() / 3600)
        if hours_passed > 0:
            team_member.action_points = min(5, team_member.action_points + hours_passed)
            team_member.last_ap_reset += timedelta(hours=hours_passed)
            db.commit()
        
    if team_member.action_points <= 0:
        return RedirectResponse(url="/dashboard?error=no_ap", status_code=302)
        
    # Check stat max limits
    if action_type == "feed" and team.hunger >= 100:
        return RedirectResponse(url="/dashboard?error=full_stat", status_code=302)
    elif action_type == "play" and team.mood >= 100:
        return RedirectResponse(url="/dashboard?error=full_stat", status_code=302)
    elif action_type == "rest" and team.energy >= 100:
        return RedirectResponse(url="/dashboard?error=full_stat", status_code=302)
        
    apply_time_decay(db, team)
    
    # Deduct AP
    team_member.action_points -= 1
    
    # Record action
    action = UserAction(user_id=current_user.id, team_id=team.id, action_type=action_type)
    db.add(action)
    
    # Update team stats (click XP is very low: 1 point)
    if action_type == "feed":
        team.hunger = min(100, team.hunger + 10)
        team.progress = min(100, team.progress + 1)
    elif action_type == "play":
        team.mood = min(100, team.mood + 10)
        team.progress = min(100, team.progress + 1)
    elif action_type == "rest":
        team.energy = min(100, team.energy + 10)
        team.progress = min(100, team.progress + 1)
    
    # Update mission progress
    today = datetime.utcnow().date()
    mission = db.query(Mission).filter(
        Mission.team_id == team.id,
        Mission.action_type == action_type,
        Mission.date >= datetime.combine(today, datetime.min.time()),
        Mission.completed == False
    ).first()
    
    if mission:
        mission.current_count += 1
        if mission.current_count >= mission.target_count:
            mission.completed = True
            team.progress = min(100, team.progress + 25)  # Large one-time bonus for completing mission
    
    # Check evolution
    team = check_evolution(team)
    
    # Decay stats slightly over time (simulated) is replaced by actual time decay in apply_time_decay
    
    team.last_updated = datetime.utcnow()
    db.commit()
    
    return RedirectResponse(url="/dashboard", status_code=302)



@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("access_token")
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
