from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, Response, Request
from fastapi.security import HTTPBearer
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
import uuid
import random
from datetime import datetime, timedelta, timezone
import bcrypt
import jwt
import cloudinary
import cloudinary.uploader
import httpx
import random

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Configuration
JWT_SECRET = os.environ.get('JWT_SECRET', 'livenow_secret_key_2025')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 7

# Cloudinary Configuration
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)

# Create the main app without a prefix
app = FastAPI(title="LiveNow API")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== Constants ====================

# Posting slots (Social)
POSTING_SLOTS = [
    {"hour": 10, "minute": 0, "name": "Morning"},
    {"hour": 14, "minute": 0, "name": "Afternoon"},
    {"hour": 22, "minute": 0, "name": "Night"}
]

# Dating Golden Hour slots
GOLDEN_HOURS = [
    {"start_hour": 10, "start_minute": 0, "end_hour": 10, "end_minute": 30, "name": "Morning Coffee", "emoji": "☀️"},
    {"start_hour": 14, "start_minute": 0, "end_hour": 14, "end_minute": 30, "name": "Lunch Break", "emoji": "🌤️"},
    {"start_hour": 22, "start_minute": 0, "end_hour": 22, "end_minute": 30, "name": "Night Owl", "emoji": "🌙"}
]

# Interest tags
INTEREST_TAGS = ["Music", "Travel", "Fitness", "Food", "Movies", "Gaming", "Reading", "Art", "Sports", "Photography"]

# ==================== Models ====================

class UserBase(BaseModel):
    email: EmailStr
    name: str
    bio: Optional[str] = ""
    profile_photo: Optional[str] = ""

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserUpdate(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    profile_photo: Optional[str] = None

class User(UserBase):
    user_id: str
    created_at: datetime
    push_token: Optional[str] = None
    post_count: int = 0
    days_active: int = 0
    dating_unlocked: bool = False
    badges: List[str] = []
    subscription_tier: str = "free"  # free, premium, elite
    is_admin: bool = False

class UserPublic(BaseModel):
    user_id: str
    name: str
    bio: Optional[str] = ""
    profile_photo: Optional[str] = ""
    badges: List[str] = []

class AuthResponse(BaseModel):
    user: User
    token: str

class PostCreate(BaseModel):
    front_image: Optional[str] = None  # Now optional - user chooses
    back_image: Optional[str] = None   # Now optional - user chooses
    photo_1: Optional[str] = None      # New: first photo (any camera)
    photo_2: Optional[str] = None      # New: second photo (any camera)
    photo_1_type: Optional[str] = "back"   # "front" or "back"
    photo_2_type: Optional[str] = "front"  # "front" or "back"
    caption: Optional[str] = ""
    mood: Optional[str] = None  # calm, bold, happy, romantic, thoughtful, golden

# Valid moods
VALID_MOODS = ["calm", "bold", "happy", "romantic", "thoughtful", "golden"]

class Post(BaseModel):
    post_id: str
    user_id: str
    front_image_url: str
    back_image_url: str
    caption: str
    mood: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    slot_name: Optional[str] = None

class PostWithUser(Post):
    user_name: str
    user_profile_photo: Optional[str] = ""
    reactions: List[dict] = []

class ReactionCreate(BaseModel):
    emoji: str

class Reaction(BaseModel):
    reaction_id: str
    post_id: str
    user_id: str
    emoji: str
    created_at: datetime

# ==================== DATING PROFILE MODELS ====================
INTEREST_OPTIONS = [
    "Gym", "Travel", "Music", "Reading", "Cooking", "Photography",
    "Art", "Gaming", "Hiking", "Yoga", "Movies", "Dancing",
    "Coffee", "Pets", "Fashion", "Tech", "Sports", "Writing",
    "Meditation", "Foodie",
]

LOOKING_FOR_OPTIONS = ["Friendship", "Dating", "Serious Relationship"]

class DatingProfileCreate(BaseModel):
    age: int
    gender: str  # male, female, other
    city: str
    bio: str
    photos: List[str] = []  # URLs of live photos (2-3 required)
    interests: List[str] = []
    looking_for: str  # Friendship, Dating, Serious Relationship

class DatingOptOutRequest(BaseModel):
    reason: Optional[str] = None

class FriendRequest(BaseModel):
    friend_user_id: str

class PushTokenUpdate(BaseModel):
    push_token: str

class GoogleAuthRequest(BaseModel):
    session_id: str

# Dating Models (DatingProfileCreate already defined above)

class DatingProfileUpdate(BaseModel):
    age: Optional[int] = None
    gender: Optional[str] = None
    looking_for: Optional[str] = None
    location: Optional[str] = None
    interests: Optional[List[str]] = None
    photos: Optional[List[str]] = None
    bio: Optional[str] = None

class DatingProfile(BaseModel):
    user_id: str
    name: str
    age: int
    gender: str
    looking_for: str
    location: str
    interests: List[str]
    photos: List[str]
    bio: str
    verified: bool = False
    created_at: datetime
    last_active: Optional[datetime] = None
    compatibility: Optional[int] = None  # Calculated field

class DatingAction(BaseModel):
    target_user_id: str
    action: str  # like, pass, superlike

class VibeCheckPhoto(BaseModel):
    photo: str  # base64

class Match(BaseModel):
    match_id: str
    user1_id: str
    user2_id: str
    created_at: datetime
    expires_at: datetime
    vibe_check_completed: bool = False
    user1_vibe_photo: Optional[str] = None
    user2_vibe_photo: Optional[str] = None
    chat_unlocked: bool = False

class DatingUnlockRequest(BaseModel):
    confirm: bool

# Chat Models
class ChatMessage(BaseModel):
    message: str
    
class ReportUser(BaseModel):
    reported_user_id: str
    reason: str  # harassment, fake_profile, spam, inappropriate, other
    details: Optional[str] = ""

class BlockUser(BaseModel):
    blocked_user_id: str

class ExtendMatch(BaseModel):
    match_id: str

# Waitlist Model
class WaitlistEntry(BaseModel):
    name: str
    age: int
    city: str
    gender: Optional[str] = ""

# Feature Flag - Dating locked for 2-3 months
DATING_LOCKED = True  # Set to False to unlock dating for all users
WAITLIST_LIMIT = 1000

# Ice Breaker Prompts
ICE_BREAKERS = [
    "Pineapple on pizza - yes or no? 🍕",
    "Morning person or night owl? 🌙",
    "Mountains or beaches? 🏔️",
    "Tea or coffee? ☕",
    "If you could travel anywhere right now? ✈️",
    "Favorite weekend activity? 🎯",
    "Dogs or cats? 🐾",
    "Last movie that made you cry? 🎬",
    "One thing on your bucket list? 🪣",
    "Your go-to comfort food? 🍜",
    "Introvert or extrovert? 🤔",
    "Describe your vibe in 3 emojis",
    "Best date you've ever been on?",
    "Your most controversial food opinion? 🍳",
    "What makes you laugh the most? 😂",
]

# Founder Pricing
FOUNDER_LIMIT = 1000
FOUNDER_DISCOUNT = 0.30  # 30%

# ==================== Helper Functions ====================

def create_jwt_token(user_id: str) -> str:
    expiration = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRATION_DAYS)
    payload = {
        "user_id": user_id,
        "exp": expiration,
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_jwt_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("user_id")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

async def get_current_user(authorization: Optional[str] = Header(None), request: Request = None) -> User:
    token = None
    
    if authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        else:
            token = authorization
    
    if not token and request:
        token = request.cookies.get("session_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_id = verify_jwt_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")
    
    return User(**user_doc)

async def upload_to_cloudinary(base64_image: str, folder: str = "livenow") -> str:
    try:
        if not base64_image.startswith("data:"):
            base64_image = f"data:image/jpeg;base64,{base64_image}"
        
        result = cloudinary.uploader.upload(
            base64_image,
            folder=folder,
            resource_type="image"
        )
        return result['secure_url']
    except Exception as e:
        logger.error(f"Cloudinary upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Image upload failed: {str(e)}")

def get_current_slot():
    """Get current posting/dating slot if active"""
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    current_minute = now.minute
    
    for slot in GOLDEN_HOURS:
        if (slot["start_hour"] == current_hour and 
            slot["start_minute"] <= current_minute < slot["end_minute"]):
            return slot
    return None

# Subscription Pricing
SUBSCRIPTION_PLANS = {
    "free": {
        "name": "Free",
        "price": 0,
        "founder_price": 0,
        "currency": "INR",
        "slots_per_day": 1,
        "matches_per_day": 3,
        "swipes_per_day": 10,
        "match_expiry_hours": 24,
        "extends_per_chat": 0,
        "features": ["1 dating slot/day", "3 matches/day", "Basic profile"],
        "badge": "",
        "priority_score": 0
    },
    "premium": {
        "name": "Premium",
        "price": 499,
        "founder_price": 349,
        "currency": "INR",
        "slots_per_day": 3,
        "matches_per_day": 6,
        "swipes_per_day": 30,
        "match_expiry_hours": 48,
        "extends_per_chat": 1,
        "features": ["3 dating slots/day", "6 matches/day", "1 chat extend/match", "Priority visibility", "Extended match (48hrs)", "Hide last seen", "Read receipts"],
        "badge": "star",
        "priority_score": 50
    },
    "elite": {
        "name": "Elite",
        "price": 999,
        "founder_price": 699,
        "currency": "INR",
        "slots_per_day": 3,
        "matches_per_day": 10,
        "swipes_per_day": 50,
        "match_expiry_hours": 48,
        "extends_per_chat": 3,
        "features": ["3 dating slots/day", "10 matches/day", "3 chat extends/match", "Top visibility", "Extended match (48hrs)", "See who liked you", "Hide last seen", "Read receipts"],
        "badge": "diamond",
        "priority_score": 100
    }
}

def calculate_compatibility(user_interests: List[str], target_interests: List[str]) -> int:
    """Calculate compatibility percentage based on shared interests"""
    if not user_interests or not target_interests:
        return 50
    
    shared = set(user_interests) & set(target_interests)
    total = set(user_interests) | set(target_interests)
    
    if not total:
        return 50
    
    return int((len(shared) / len(total)) * 100)

async def check_dating_unlock(user_id: str) -> dict:
    """Check if user can unlock dating"""
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        return {"can_unlock": False, "reason": "User not found"}
    
    days_active = user.get("days_active", 0)
    post_count = user.get("post_count", 0)
    
    # Check if already unlocked
    if user.get("dating_unlocked", False):
        return {"can_unlock": True, "already_unlocked": True}
    
    # 3 days OR 5 posts to unlock
    if days_active >= 3 or post_count >= 5:
        return {"can_unlock": True, "already_unlocked": False}
    
    return {
        "can_unlock": False,
        "days_active": days_active,
        "post_count": post_count,
        "days_needed": max(0, 3 - days_active),
        "posts_needed": max(0, 5 - post_count)
    }

async def update_user_activity(user_id: str):
    """Update user's activity tracking"""
    today = datetime.now(timezone.utc).date()
    
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        return
    
    last_active_date = user.get("last_active_date")
    
    if last_active_date:
        last_active = datetime.fromisoformat(last_active_date).date() if isinstance(last_active_date, str) else last_active_date.date()
        if last_active != today:
            # New day, increment days_active
            await db.users.update_one(
                {"user_id": user_id},
                {
                    "$inc": {"days_active": 1},
                    "$set": {"last_active_date": today.isoformat()}
                }
            )
    else:
        await db.users.update_one(
            {"user_id": user_id},
            {
                "$set": {"days_active": 1, "last_active_date": today.isoformat()}
            }
        )
    
    # Check for badges
    await check_and_award_badges(user_id)

async def check_and_award_badges(user_id: str):
    """Check and award badges based on activity"""
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        return
    
    badges = user.get("badges", [])
    days_active = user.get("days_active", 0)
    post_count = user.get("post_count", 0)
    
    new_badges = []
    
    # Activity badges
    if days_active >= 3 and "3_day_active" not in badges:
        new_badges.append("3_day_active")
    
    if days_active >= 7 and "7_day_streak" not in badges:
        new_badges.append("7_day_streak")
    
    if days_active >= 30 and "verified_regular" not in badges:
        new_badges.append("verified_regular")
    
    # Post badges
    if post_count >= 5 and "5_posts" not in badges:
        new_badges.append("5_posts")
    
    # Match badge
    match_count = await db.matches.count_documents({
        "$or": [{"user1_id": user_id}, {"user2_id": user_id}]
    })
    if match_count >= 1 and "first_match" not in badges:
        new_badges.append("first_match")
    
    # Vibe check badge
    vibe_count = await db.matches.count_documents({
        "$or": [
            {"user1_id": user_id, "user1_vibe_photo": {"$ne": None}},
            {"user2_id": user_id, "user2_vibe_photo": {"$ne": None}}
        ]
    })
    if vibe_count >= 5 and "vibe_checker" not in badges:
        new_badges.append("vibe_checker")
    
    # Friends badge
    friend_count = await db.friendships.count_documents({
        "$and": [
            {"status": "accepted"},
            {"$or": [{"requester_id": user_id}, {"addressee_id": user_id}]}
        ]
    })
    if friend_count >= 10 and "social_butterfly" not in badges:
        new_badges.append("social_butterfly")
    
    if new_badges:
        await db.users.update_one(
            {"user_id": user_id},
            {"$push": {"badges": {"$each": new_badges}}}
        )

# ==================== Auth Routes ====================

@api_router.post("/auth/register", response_model=AuthResponse)
async def register(user_data: UserCreate):
    existing = await db.users.find_one({"email": user_data.email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    hashed_pw = hash_password(user_data.password)
    
    user_doc = {
        "user_id": user_id,
        "email": user_data.email,
        "name": user_data.name,
        "password_hash": hashed_pw,
        "bio": "",
        "profile_photo": "",
        "push_token": None,
        "created_at": datetime.now(timezone.utc),
        "post_count": 0,
        "days_active": 1,
        "dating_unlocked": False,
        "badges": [],
        "subscription_tier": "free",
        "last_active_date": datetime.now(timezone.utc).date().isoformat()
    }
    
    await db.users.insert_one(user_doc)
    
    token = create_jwt_token(user_id)
    user = User(**user_doc)
    
    return AuthResponse(user=user, token=token)

@api_router.post("/auth/login", response_model=AuthResponse)
async def login(credentials: UserLogin):
    user_doc = await db.users.find_one({"email": credentials.email}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not verify_password(credentials.password, user_doc.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Update activity
    await update_user_activity(user_doc["user_id"])
    
    token = create_jwt_token(user_doc["user_id"])
    user = User(**user_doc)
    
    return AuthResponse(user=user, token=token)

@api_router.post("/auth/google", response_model=AuthResponse)
async def google_auth(auth_data: GoogleAuthRequest, response: Response):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": auth_data.session_id}
            )
            
            if resp.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid session")
            
            google_data = resp.json()
    except Exception as e:
        logger.error(f"Google auth error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")
    
    email = google_data.get("email")
    name = google_data.get("name", "")
    picture = google_data.get("picture", "")
    
    existing_user = await db.users.find_one({"email": email}, {"_id": 0})
    
    if existing_user:
        user_id = existing_user["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": name, "profile_photo": picture}}
        )
        await update_user_activity(user_id)
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user_doc = {
            "user_id": user_id,
            "email": email,
            "name": name,
            "password_hash": "",
            "bio": "",
            "profile_photo": picture,
            "push_token": None,
            "created_at": datetime.now(timezone.utc),
            "post_count": 0,
            "days_active": 1,
            "dating_unlocked": False,
            "badges": [],
            "subscription_tier": "free",
            "last_active_date": datetime.now(timezone.utc).date().isoformat()
        }
        await db.users.insert_one(user_doc)
    
    token = create_jwt_token(user_id)
    
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=JWT_EXPIRATION_DAYS * 24 * 60 * 60,
        path="/"
    )
    
    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    user = User(**user_doc)
    
    return AuthResponse(user=user, token=token)

@api_router.get("/auth/me", response_model=User)
async def get_me(current_user: User = Depends(get_current_user)):
    await update_user_activity(current_user.user_id)
    # Refresh user data
    user_doc = await db.users.find_one({"user_id": current_user.user_id}, {"_id": 0})
    return User(**user_doc)

@api_router.post("/auth/logout")
async def logout(response: Response, current_user: User = Depends(get_current_user)):
    response.delete_cookie(key="session_token", path="/")
    return {"message": "Logged out successfully"}

# ==================== User Routes ====================

@api_router.put("/users/me", response_model=User)
async def update_profile(update_data: UserUpdate, current_user: User = Depends(get_current_user)):
    update_dict = {}
    if update_data.name is not None:
        update_dict["name"] = update_data.name
    if update_data.bio is not None:
        update_dict["bio"] = update_data.bio
    if update_data.profile_photo is not None:
        if update_data.profile_photo.startswith("data:") or len(update_data.profile_photo) > 200:
            update_dict["profile_photo"] = await upload_to_cloudinary(update_data.profile_photo, "livenow/profiles")
        else:
            update_dict["profile_photo"] = update_data.profile_photo
    
    if update_dict:
        await db.users.update_one(
            {"user_id": current_user.user_id},
            {"$set": update_dict}
        )
    
    user_doc = await db.users.find_one({"user_id": current_user.user_id}, {"_id": 0})
    return User(**user_doc)

@api_router.put("/users/push-token")
async def update_push_token(token_data: PushTokenUpdate, current_user: User = Depends(get_current_user)):
    await db.users.update_one(
        {"user_id": current_user.user_id},
        {"$set": {"push_token": token_data.push_token}}
    )
    return {"message": "Push token updated"}

@api_router.get("/users/search", response_model=List[UserPublic])
async def search_users(q: str, current_user: User = Depends(get_current_user)):
    users = await db.users.find(
        {
            "$and": [
                {"user_id": {"$ne": current_user.user_id}},
                {"$or": [
                    {"name": {"$regex": q, "$options": "i"}},
                    {"email": {"$regex": q, "$options": "i"}}
                ]}
            ]
        },
        {"_id": 0, "user_id": 1, "name": 1, "bio": 1, "profile_photo": 1, "badges": 1}
    ).to_list(20)
    
    return [UserPublic(**user) for user in users]

@api_router.get("/users/{user_id}", response_model=UserPublic)
async def get_user(user_id: str, current_user: User = Depends(get_current_user)):
    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPublic(**user_doc)

# ==================== Friend Routes ====================

@api_router.post("/friends/request")
async def send_friend_request(request_data: FriendRequest, current_user: User = Depends(get_current_user)):
    friend_id = request_data.friend_user_id
    
    if friend_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Cannot send friend request to yourself")
    
    friend = await db.users.find_one({"user_id": friend_id}, {"_id": 0})
    if not friend:
        raise HTTPException(status_code=404, detail="User not found")
    
    existing = await db.friendships.find_one({
        "$or": [
            {"requester_id": current_user.user_id, "addressee_id": friend_id},
            {"requester_id": friend_id, "addressee_id": current_user.user_id}
        ]
    }, {"_id": 0})
    
    if existing:
        if existing["status"] == "accepted":
            raise HTTPException(status_code=400, detail="Already friends")
        elif existing["status"] == "pending":
            raise HTTPException(status_code=400, detail="Friend request already pending")
    
    friendship_id = f"friend_{uuid.uuid4().hex[:12]}"
    friendship = {
        "friendship_id": friendship_id,
        "requester_id": current_user.user_id,
        "addressee_id": friend_id,
        "status": "pending",
        "created_at": datetime.now(timezone.utc)
    }
    
    await db.friendships.insert_one(friendship)
    return {"message": "Friend request sent", "friendship_id": friendship_id}

@api_router.get("/friends/requests", response_model=List[dict])
async def get_friend_requests(current_user: User = Depends(get_current_user)):
    requests = await db.friendships.find(
        {"addressee_id": current_user.user_id, "status": "pending"},
        {"_id": 0}
    ).to_list(100)
    
    result = []
    for req in requests:
        requester = await db.users.find_one({"user_id": req["requester_id"]}, {"_id": 0})
        if requester:
            result.append({
                "friendship_id": req["friendship_id"],
                "requester": UserPublic(**requester).model_dump(),
                "created_at": req["created_at"]
            })
    
    return result

@api_router.put("/friends/{friendship_id}/accept")
async def accept_friend_request(friendship_id: str, current_user: User = Depends(get_current_user)):
    friendship = await db.friendships.find_one(
        {"friendship_id": friendship_id, "addressee_id": current_user.user_id, "status": "pending"},
        {"_id": 0}
    )
    
    if not friendship:
        raise HTTPException(status_code=404, detail="Friend request not found")
    
    await db.friendships.update_one(
        {"friendship_id": friendship_id},
        {"$set": {"status": "accepted"}}
    )
    
    return {"message": "Friend request accepted"}

@api_router.put("/friends/{friendship_id}/reject")
async def reject_friend_request(friendship_id: str, current_user: User = Depends(get_current_user)):
    friendship = await db.friendships.find_one(
        {"friendship_id": friendship_id, "addressee_id": current_user.user_id, "status": "pending"},
        {"_id": 0}
    )
    
    if not friendship:
        raise HTTPException(status_code=404, detail="Friend request not found")
    
    await db.friendships.update_one(
        {"friendship_id": friendship_id},
        {"$set": {"status": "rejected"}}
    )
    
    return {"message": "Friend request rejected"}

@api_router.get("/friends", response_model=List[UserPublic])
async def get_friends(current_user: User = Depends(get_current_user)):
    friendships = await db.friendships.find(
        {
            "$and": [
                {"status": "accepted"},
                {"$or": [
                    {"requester_id": current_user.user_id},
                    {"addressee_id": current_user.user_id}
                ]}
            ]
        },
        {"_id": 0}
    ).to_list(1000)
    
    friend_ids = []
    for f in friendships:
        if f["requester_id"] == current_user.user_id:
            friend_ids.append(f["addressee_id"])
        else:
            friend_ids.append(f["requester_id"])
    
    friends = await db.users.find(
        {"user_id": {"$in": friend_ids}},
        {"_id": 0, "user_id": 1, "name": 1, "bio": 1, "profile_photo": 1, "badges": 1}
    ).to_list(1000)
    
    return [UserPublic(**f) for f in friends]

@api_router.delete("/friends/{friend_user_id}")
async def remove_friend(friend_user_id: str, current_user: User = Depends(get_current_user)):
    result = await db.friendships.delete_one({
        "$and": [
            {"status": "accepted"},
            {"$or": [
                {"requester_id": current_user.user_id, "addressee_id": friend_user_id},
                {"requester_id": friend_user_id, "addressee_id": current_user.user_id}
            ]}
        ]
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Friendship not found")
    
    return {"message": "Friend removed"}

# ==================== Post Routes ====================

@api_router.post("/posts", response_model=Post)
async def create_post(post_data: PostCreate, current_user: User = Depends(get_current_user)):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    existing_post = await db.posts.find_one({
        "user_id": current_user.user_id,
        "created_at": {"$gte": today_start}
    }, {"_id": 0})
    
    if existing_post:
        raise HTTPException(status_code=400, detail="You can only post once per day")
    
    # Support both old (front_image/back_image) and new (photo_1/photo_2) formats
    if post_data.photo_1:
        # New format: user chose which camera for each photo
        photo_1_url = await upload_to_cloudinary(post_data.photo_1, "livenow/posts")
        photo_2_url = await upload_to_cloudinary(post_data.photo_2, "livenow/posts") if post_data.photo_2 else photo_1_url
        
        # Map to front/back based on camera type
        if post_data.photo_1_type == "front":
            front_url, back_url = photo_1_url, photo_2_url
        else:
            front_url, back_url = photo_2_url, photo_1_url
    else:
        # Legacy format
        front_url = await upload_to_cloudinary(post_data.front_image, "livenow/posts")
        back_url = await upload_to_cloudinary(post_data.back_image, "livenow/posts")
    
    # Validate mood
    mood = post_data.mood
    if mood and mood not in VALID_MOODS:
        mood = None
    
    # Determine current slot
    current_slot = get_current_slot()
    slot_name = current_slot["name"] if current_slot else "Open"
    
    post_id = f"post_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=24)
    
    post_doc = {
        "post_id": post_id,
        "user_id": current_user.user_id,
        "front_image_url": front_url,
        "back_image_url": back_url,
        "caption": post_data.caption or "",
        "mood": mood,
        "created_at": now,
        "expires_at": expires,
        "slot_name": slot_name
    }
    
    await db.posts.insert_one(post_doc)
    
    # Increment post count
    await db.users.update_one(
        {"user_id": current_user.user_id},
        {"$inc": {"post_count": 1}}
    )
    
    return Post(**post_doc)

@api_router.get("/posts/feed", response_model=List[PostWithUser])
async def get_feed(current_user: User = Depends(get_current_user)):
    friendships = await db.friendships.find(
        {
            "$and": [
                {"status": "accepted"},
                {"$or": [
                    {"requester_id": current_user.user_id},
                    {"addressee_id": current_user.user_id}
                ]}
            ]
        },
        {"_id": 0}
    ).to_list(1000)
    
    friend_ids = [current_user.user_id]
    for f in friendships:
        if f["requester_id"] == current_user.user_id:
            friend_ids.append(f["addressee_id"])
        else:
            friend_ids.append(f["requester_id"])
    
    now = datetime.now(timezone.utc)
    
    posts = await db.posts.find(
        {
            "user_id": {"$in": friend_ids},
            "expires_at": {"$gt": now}
        },
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    
    result = []
    for post in posts:
        user = await db.users.find_one({"user_id": post["user_id"]}, {"_id": 0})
        reactions = await db.reactions.find({"post_id": post["post_id"]}, {"_id": 0}).to_list(100)
        
        result.append(PostWithUser(
            **post,
            user_name=user["name"] if user else "Unknown",
            user_profile_photo=user.get("profile_photo", "") if user else "",
            reactions=reactions
        ))
    
    return result

@api_router.get("/posts/my", response_model=Optional[PostWithUser])
async def get_my_todays_post(current_user: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    
    post = await db.posts.find_one({
        "user_id": current_user.user_id,
        "expires_at": {"$gt": now}
    }, {"_id": 0})
    
    if not post:
        return None
    
    reactions = await db.reactions.find({"post_id": post["post_id"]}, {"_id": 0}).to_list(100)
    
    return PostWithUser(
        **post,
        user_name=current_user.name,
        user_profile_photo=current_user.profile_photo or "",
        reactions=reactions
    )

@api_router.delete("/posts/{post_id}")
async def delete_post(post_id: str, current_user: User = Depends(get_current_user)):
    post = await db.posts.find_one({"post_id": post_id, "user_id": current_user.user_id}, {"_id": 0})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    await db.posts.delete_one({"post_id": post_id})
    await db.reactions.delete_many({"post_id": post_id})
    
    return {"message": "Post deleted"}

# ==================== Reaction Routes ====================

@api_router.post("/posts/{post_id}/reactions", response_model=Reaction)
async def add_reaction(post_id: str, reaction_data: ReactionCreate, current_user: User = Depends(get_current_user)):
    post = await db.posts.find_one({"post_id": post_id}, {"_id": 0})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    existing = await db.reactions.find_one({
        "post_id": post_id,
        "user_id": current_user.user_id,
        "emoji": reaction_data.emoji
    }, {"_id": 0})
    
    if existing:
        raise HTTPException(status_code=400, detail="Already reacted with this emoji")
    
    reaction_id = f"react_{uuid.uuid4().hex[:12]}"
    reaction = {
        "reaction_id": reaction_id,
        "post_id": post_id,
        "user_id": current_user.user_id,
        "emoji": reaction_data.emoji,
        "created_at": datetime.now(timezone.utc)
    }
    
    await db.reactions.insert_one(reaction)
    return Reaction(**reaction)

@api_router.delete("/posts/{post_id}/reactions/{emoji}")
async def remove_reaction(post_id: str, emoji: str, current_user: User = Depends(get_current_user)):
    result = await db.reactions.delete_one({
        "post_id": post_id,
        "user_id": current_user.user_id,
        "emoji": emoji
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Reaction not found")
    
    return {"message": "Reaction removed"}

# ==================== Notification Routes ====================

@api_router.get("/notifications/slots")
async def get_posting_slots():
    """Get the daily posting slots"""
    return {
        "slots": POSTING_SLOTS,
        "current_slot": get_current_slot()
    }

@api_router.get("/notifications/daily-time")
async def get_daily_notification_time():
    """Get the next notification time"""
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    
    # Find next slot
    for slot in POSTING_SLOTS:
        if slot["hour"] > current_hour:
            return {"hour": slot["hour"], "minute": slot["minute"], "name": slot["name"]}
    
    # Return first slot of next day
    return {"hour": POSTING_SLOTS[0]["hour"], "minute": POSTING_SLOTS[0]["minute"], "name": POSTING_SLOTS[0]["name"]}

# ==================== Dating Routes ====================

@api_router.get("/dating/unlock-status")
async def get_dating_unlock_status(current_user: User = Depends(get_current_user)):
    """Check if user can unlock dating"""
    return await check_dating_unlock(current_user.user_id)

@api_router.post("/dating/unlock")
async def unlock_dating(unlock_data: DatingUnlockRequest, current_user: User = Depends(get_current_user)):
    """Unlock dating feature"""
    if not unlock_data.confirm:
        raise HTTPException(status_code=400, detail="Please confirm to unlock dating")
    
    status = await check_dating_unlock(current_user.user_id)
    
    if not status["can_unlock"]:
        raise HTTPException(status_code=400, detail="Cannot unlock dating yet")
    
    if status.get("already_unlocked"):
        return {"message": "Dating already unlocked", "dating_unlocked": True}
    
    await db.users.update_one(
        {"user_id": current_user.user_id},
        {"$set": {"dating_unlocked": True}}
    )
    
    return {"message": "Dating unlocked successfully!", "dating_unlocked": True}

@api_router.get("/dating/golden-hours")
async def get_golden_hours(current_user: User = Depends(get_current_user)):
    """Get the dating golden hour slots"""
    current = get_current_slot()
    return {
        "slots": GOLDEN_HOURS,
        "current_slot": current,
        "is_active": current is not None
    }

@api_router.get("/dating/interests")
async def get_interest_tags():
    """Get available interest tags"""
    return {"interests": INTEREST_TAGS}

@api_router.post("/dating/profile")
async def create_dating_profile(profile_data: DatingProfileCreate, current_user: User = Depends(get_current_user)):
    """Create or update dating profile"""
    # Check if dating is unlocked
    if not current_user.dating_unlocked:
        raise HTTPException(status_code=403, detail="Dating not unlocked yet")
    
    # Validate age
    if profile_data.age < 18:
        raise HTTPException(status_code=400, detail="Must be 18+ to use dating")
    
    # Upload photos to Cloudinary
    photo_urls = []
    for photo in profile_data.photos[:3]:  # Max 3 photos
        if photo.startswith("data:") or len(photo) > 200:
            url = await upload_to_cloudinary(photo, "livenow/dating")
            photo_urls.append(url)
        else:
            photo_urls.append(photo)
    
    profile_doc = {
        "user_id": current_user.user_id,
        "name": current_user.name,
        "age": profile_data.age,
        "gender": profile_data.gender,
        "looking_for": profile_data.looking_for,
        "location": profile_data.location or "",
        "interests": profile_data.interests[:6],  # Max 6 interests
        "photos": photo_urls,
        "bio": profile_data.bio or "",
        "verified": len(current_user.badges) > 0,
        "created_at": datetime.now(timezone.utc),
        "last_active": datetime.now(timezone.utc)
    }
    
    # Upsert profile
    await db.dating_profiles.update_one(
        {"user_id": current_user.user_id},
        {"$set": profile_doc},
        upsert=True
    )
    
    return {"message": "Dating profile created", "profile": profile_doc}

@api_router.get("/dating/profile", response_model=Optional[DatingProfile])
async def get_my_dating_profile(current_user: User = Depends(get_current_user)):
    """Get current user's dating profile"""
    profile = await db.dating_profiles.find_one({"user_id": current_user.user_id}, {"_id": 0})
    if not profile:
        return None
    return DatingProfile(**profile)

@api_router.put("/dating/profile")
async def update_dating_profile(profile_data: DatingProfileUpdate, current_user: User = Depends(get_current_user)):
    """Update dating profile"""
    update_dict = {}
    
    if profile_data.age is not None:
        if profile_data.age < 18:
            raise HTTPException(status_code=400, detail="Must be 18+")
        update_dict["age"] = profile_data.age
    
    if profile_data.gender is not None:
        update_dict["gender"] = profile_data.gender
    
    if profile_data.looking_for is not None:
        update_dict["looking_for"] = profile_data.looking_for
    
    if profile_data.location is not None:
        update_dict["location"] = profile_data.location
    
    if profile_data.interests is not None:
        update_dict["interests"] = profile_data.interests[:6]
    
    if profile_data.bio is not None:
        update_dict["bio"] = profile_data.bio
    
    if profile_data.photos is not None:
        photo_urls = []
        for photo in profile_data.photos[:3]:
            if photo.startswith("data:") or len(photo) > 200:
                url = await upload_to_cloudinary(photo, "livenow/dating")
                photo_urls.append(url)
            else:
                photo_urls.append(photo)
        update_dict["photos"] = photo_urls
    
    update_dict["last_active"] = datetime.now(timezone.utc)
    
    if update_dict:
        await db.dating_profiles.update_one(
            {"user_id": current_user.user_id},
            {"$set": update_dict}
        )
    
    profile = await db.dating_profiles.find_one({"user_id": current_user.user_id}, {"_id": 0})
    return {"message": "Profile updated", "profile": profile}

@api_router.get("/dating/discover", response_model=List[DatingProfile])
async def discover_profiles(current_user: User = Depends(get_current_user)):
    """Get profiles to swipe on during golden hour"""
    if not current_user.dating_unlocked:
        raise HTTPException(status_code=403, detail="Dating not unlocked")
    
    # Check if golden hour is active
    current_slot = get_current_slot()
    # For demo, allow discovery anytime
    # if not current_slot:
    #     raise HTTPException(status_code=400, detail="Dating only available during Golden Hours")
    
    # Get user's dating profile
    my_profile = await db.dating_profiles.find_one({"user_id": current_user.user_id}, {"_id": 0})
    if not my_profile:
        raise HTTPException(status_code=400, detail="Please create your dating profile first")
    
    # Get already swiped users today
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    swiped = await db.dating_actions.find(
        {"user_id": current_user.user_id, "created_at": {"$gte": today_start}},
        {"_id": 0, "target_user_id": 1}
    ).to_list(1000)
    swiped_ids = [s["target_user_id"] for s in swiped]
    swiped_ids.append(current_user.user_id)  # Exclude self
    
    # Build query based on preferences
    query = {"user_id": {"$nin": swiped_ids}}
    
    # Exclude blocked users
    blocks = await db.blocks.find(
        {"$or": [{"blocker_id": current_user.user_id}, {"blocked_id": current_user.user_id}]},
        {"_id": 0}
    ).to_list(1000)
    blocked_ids = set()
    for block in blocks:
        blocked_ids.add(block.get("blocker_id", ""))
        blocked_ids.add(block.get("blocked_id", ""))
    blocked_ids.discard(current_user.user_id)
    if blocked_ids:
        query["user_id"]["$nin"] = swiped_ids + list(blocked_ids)
    
    looking_for = my_profile.get("looking_for", "everyone")
    if looking_for != "everyone":
        query["gender"] = looking_for
    
    # Get profiles
    profiles = await db.dating_profiles.find(query, {"_id": 0}).limit(30).to_list(30)
    
    # Calculate compatibility and add tier priority
    my_interests = my_profile.get("interests", [])
    result = []
    for profile in profiles:
        compatibility = calculate_compatibility(my_interests, profile.get("interests", []))
        profile["compatibility"] = compatibility
        
        # Get user's subscription tier for priority sorting
        user_doc = await db.users.find_one({"user_id": profile["user_id"]}, {"_id": 0, "subscription_tier": 1})
        tier = user_doc.get("subscription_tier", "free") if user_doc else "free"
        profile["_tier_priority"] = SUBSCRIPTION_PLANS.get(tier, {}).get("priority_score", 0)
        
        result.append(profile)
    
    # Sort by tier priority first, then compatibility
    result.sort(key=lambda x: (x.get("_tier_priority", 0), x.get("compatibility", 0)), reverse=True)
    
    # Clean up internal fields and convert
    final = []
    for p in result:
        p.pop("_tier_priority", None)
        final.append(DatingProfile(**p))
    
    return final

@api_router.post("/dating/action")
async def dating_action(action_data: DatingAction, current_user: User = Depends(get_current_user)):
    """Like, Pass, or Superlike a profile"""
    if not current_user.dating_unlocked:
        raise HTTPException(status_code=403, detail="Dating not unlocked")
    
    # Check daily limits based on subscription
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    actions_today = await db.dating_actions.count_documents({
        "user_id": current_user.user_id,
        "created_at": {"$gte": today_start}
    })
    
    # Limits based on tier
    limits = {"free": 10, "premium": 30, "elite": 50}
    user_limit = limits.get(current_user.subscription_tier, 10)
    
    if actions_today >= user_limit:
        raise HTTPException(status_code=400, detail="Daily swipe limit reached")
    
    # Record action
    action_doc = {
        "action_id": f"action_{uuid.uuid4().hex[:12]}",
        "user_id": current_user.user_id,
        "target_user_id": action_data.target_user_id,
        "action": action_data.action,
        "created_at": datetime.now(timezone.utc)
    }
    
    await db.dating_actions.insert_one(action_doc)
    
    # Check for match if action is like or superlike
    if action_data.action in ["like", "superlike"]:
        # Check if target has already liked us
        reverse_like = await db.dating_actions.find_one({
            "user_id": action_data.target_user_id,
            "target_user_id": current_user.user_id,
            "action": {"$in": ["like", "superlike"]}
        }, {"_id": 0})
        
        if reverse_like:
            # It's a match!
            # Check match limits
            matches_today = await db.matches.count_documents({
                "$or": [
                    {"user1_id": current_user.user_id},
                    {"user2_id": current_user.user_id}
                ],
                "created_at": {"$gte": today_start}
            })
            
            match_limits = {"free": 3, "premium": 6, "elite": 10}
            match_limit = match_limits.get(current_user.subscription_tier, 3)
            
            if matches_today < match_limit:
                # Determine expiry based on tier
                expiry_hours = 24 if current_user.subscription_tier == "free" else 48
                
                match_doc = {
                    "match_id": f"match_{uuid.uuid4().hex[:12]}",
                    "user1_id": current_user.user_id,
                    "user2_id": action_data.target_user_id,
                    "created_at": datetime.now(timezone.utc),
                    "expires_at": datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
                    "vibe_check_deadline": datetime.now(timezone.utc) + timedelta(minutes=5),
                    "vibe_check_completed": False,
                    "user1_vibe_photo": None,
                    "user2_vibe_photo": None,
                    "chat_unlocked": False,
                    "status": "active"
                }
                
                await db.matches.insert_one(match_doc)
                
                return {
                    "message": "It's a match!",
                    "is_match": True,
                    "match_id": match_doc["match_id"]
                }
    
    return {"message": "Action recorded", "is_match": False}

@api_router.get("/dating/matches", response_model=List[dict])
async def get_matches(current_user: User = Depends(get_current_user)):
    """Get current user's matches"""
    if not current_user.dating_unlocked:
        raise HTTPException(status_code=403, detail="Dating not unlocked")
    
    now = datetime.now(timezone.utc)
    
    matches = await db.matches.find({
        "$or": [
            {"user1_id": current_user.user_id},
            {"user2_id": current_user.user_id}
        ],
        "expires_at": {"$gt": now}
    }, {"_id": 0}).to_list(100)
    
    result = []
    for match in matches:
        # Get the other user
        other_user_id = match["user2_id"] if match["user1_id"] == current_user.user_id else match["user1_id"]
        other_profile = await db.dating_profiles.find_one({"user_id": other_user_id}, {"_id": 0})
        
        if other_profile:
            result.append({
                "match": match,
                "profile": other_profile
            })
    
    return result

@api_router.post("/dating/matches/{match_id}/vibe-check")
async def submit_vibe_check(match_id: str, photo_data: VibeCheckPhoto, current_user: User = Depends(get_current_user)):
    """Submit vibe check photo - must be within 5 minutes of match"""
    match = await db.matches.find_one({"match_id": match_id}, {"_id": 0})
    
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    if current_user.user_id not in [match["user1_id"], match["user2_id"]]:
        raise HTTPException(status_code=403, detail="Not your match")
    
    # Check vibe check deadline (5 minute window)
    deadline = match.get("vibe_check_deadline")
    if deadline:
        if isinstance(deadline, str):
            deadline = datetime.fromisoformat(deadline)
        if datetime.now(timezone.utc) > deadline:
            # Mark match as expired vibe check
            await db.matches.update_one(
                {"match_id": match_id},
                {"$set": {"status": "vibe_check_expired"}}
            )
            raise HTTPException(status_code=400, detail="Vibe check window expired (5 minutes). The match is still active but vibe check timed out.")
    
    if match.get("vibe_check_completed"):
        raise HTTPException(status_code=400, detail="Vibe check already completed")
    
    # Upload photo
    photo_url = await upload_to_cloudinary(photo_data.photo, "livenow/vibecheck")
    
    # Update match
    if current_user.user_id == match["user1_id"]:
        update_field = "user1_vibe_photo"
    else:
        update_field = "user2_vibe_photo"
    
    await db.matches.update_one(
        {"match_id": match_id},
        {"$set": {update_field: photo_url}}
    )
    
    # Check if both have submitted
    updated_match = await db.matches.find_one({"match_id": match_id}, {"_id": 0})
    
    if updated_match["user1_vibe_photo"] and updated_match["user2_vibe_photo"]:
        await db.matches.update_one(
            {"match_id": match_id},
            {"$set": {"vibe_check_completed": True, "chat_unlocked": True, "status": "chat_ready"}}
        )
        return {"message": "Vibe check complete! Chat unlocked.", "chat_unlocked": True}
    
    return {"message": "Vibe check photo submitted. Waiting for match.", "chat_unlocked": False}

@api_router.get("/dating/stats")
async def get_dating_stats(current_user: User = Depends(get_current_user)):
    """Get user's dating statistics"""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Count today's actions
    actions_today = await db.dating_actions.count_documents({
        "user_id": current_user.user_id,
        "created_at": {"$gte": today_start}
    })
    
    # Count today's matches
    matches_today = await db.matches.count_documents({
        "$or": [
            {"user1_id": current_user.user_id},
            {"user2_id": current_user.user_id}
        ],
        "created_at": {"$gte": today_start}
    })
    
    # Limits
    limits = {"free": 10, "premium": 30, "elite": 50}
    match_limits = {"free": 3, "premium": 6, "elite": 10}
    
    tier = current_user.subscription_tier
    
    return {
        "swipes_used": actions_today,
        "swipes_limit": limits.get(tier, 10),
        "matches_today": matches_today,
        "matches_limit": match_limits.get(tier, 3),
        "tier": tier
    }

@api_router.get("/dating/subscription-plans")
async def get_subscription_plans():
    """Get available subscription plans with founder pricing"""
    total_users = await db.users.count_documents({})
    is_founder_active = total_users < FOUNDER_LIMIT
    spots_remaining = max(0, FOUNDER_LIMIT - total_users)
    
    plans_with_pricing = {}
    for key, plan in SUBSCRIPTION_PLANS.items():
        p = {**plan}
        if is_founder_active and key != "free":
            p["active_price"] = p["founder_price"]
            p["is_founder_price"] = True
        else:
            p["active_price"] = p["price"]
            p["is_founder_price"] = False
        plans_with_pricing[key] = p
    
    return {
        "plans": plans_with_pricing,
        "founder_active": is_founder_active,
        "founder_spots_remaining": spots_remaining,
        "founder_discount_percent": int(FOUNDER_DISCOUNT * 100)
    }

@api_router.post("/dating/subscribe/{plan}")
async def subscribe_plan(plan: str, current_user: User = Depends(get_current_user)):
    """Subscribe to a plan (mock - no payment gateway)"""
    if plan not in SUBSCRIPTION_PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    if plan == "free":
        raise HTTPException(status_code=400, detail="You're already on free plan")
    
    await db.users.update_one(
        {"user_id": current_user.user_id},
        {"$set": {"subscription_tier": plan}}
    )
    
    return {
        "message": f"Subscribed to {SUBSCRIPTION_PLANS[plan]['name']}!",
        "plan": SUBSCRIPTION_PLANS[plan],
        "tier": plan
    }

# ==================== Chat Routes ====================

@api_router.post("/chat/{match_id}/send")
async def send_message(match_id: str, msg: ChatMessage, current_user: User = Depends(get_current_user)):
    """Send a message in a match chat"""
    match = await db.matches.find_one({"match_id": match_id}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    if current_user.user_id not in [match["user1_id"], match["user2_id"]]:
        raise HTTPException(status_code=403, detail="Not your match")
    
    # Check if match expired
    if datetime.now(timezone.utc) > match["expires_at"]:
        raise HTTPException(status_code=400, detail="Match has expired")
    
    # Check if blocked
    other_id = match["user2_id"] if match["user1_id"] == current_user.user_id else match["user1_id"]
    blocked = await db.blocks.find_one({
        "$or": [
            {"blocker_id": current_user.user_id, "blocked_id": other_id},
            {"blocker_id": other_id, "blocked_id": current_user.user_id}
        ]
    })
    if blocked:
        raise HTTPException(status_code=403, detail="Cannot send message")
    
    message_doc = {
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
        "match_id": match_id,
        "sender_id": current_user.user_id,
        "receiver_id": other_id,
        "message": msg.message,
        "read": False,
        "created_at": datetime.now(timezone.utc)
    }
    
    await db.messages.insert_one(message_doc)
    
    # Update last_active for sender
    await db.dating_profiles.update_one(
        {"user_id": current_user.user_id},
        {"$set": {"last_active": datetime.now(timezone.utc)}}
    )
    
    # Check/update match streak
    await update_chat_streak(match_id, current_user.user_id)
    
    return {**message_doc, "_id": None}

@api_router.get("/chat/{match_id}/messages")
async def get_messages(match_id: str, limit: int = 50, current_user: User = Depends(get_current_user)):
    """Get chat messages for a match"""
    match = await db.matches.find_one({"match_id": match_id}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    if current_user.user_id not in [match["user1_id"], match["user2_id"]]:
        raise HTTPException(status_code=403, detail="Not your match")
    
    messages = await db.messages.find(
        {"match_id": match_id},
        {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(limit)
    
    # Mark unread messages as read
    await db.messages.update_many(
        {"match_id": match_id, "receiver_id": current_user.user_id, "read": False},
        {"$set": {"read": True, "read_at": datetime.now(timezone.utc)}}
    )
    
    messages.reverse()
    return messages

@api_router.post("/chat/{match_id}/typing")
async def set_typing(match_id: str, current_user: User = Depends(get_current_user)):
    """Set typing indicator"""
    await db.typing_indicators.update_one(
        {"match_id": match_id, "user_id": current_user.user_id},
        {"$set": {"typing": True, "updated_at": datetime.now(timezone.utc)}},
        upsert=True
    )
    return {"status": "typing"}

@api_router.get("/chat/{match_id}/typing")
async def get_typing(match_id: str, current_user: User = Depends(get_current_user)):
    """Check if other user is typing"""
    match = await db.matches.find_one({"match_id": match_id}, {"_id": 0})
    if not match:
        return {"is_typing": False}
    
    other_id = match["user2_id"] if match["user1_id"] == current_user.user_id else match["user1_id"]
    
    indicator = await db.typing_indicators.find_one(
        {"match_id": match_id, "user_id": other_id}, {"_id": 0}
    )
    
    if indicator and indicator.get("typing"):
        # Check if typing was set within last 5 seconds
        if (datetime.now(timezone.utc) - indicator["updated_at"]).total_seconds() < 5:
            return {"is_typing": True}
    
    return {"is_typing": False}

@api_router.get("/chat/{match_id}/ice-breaker")
async def get_ice_breaker(match_id: str, current_user: User = Depends(get_current_user)):
    """Get random ice breaker prompts for chat"""
    prompts = random.sample(ICE_BREAKERS, min(3, len(ICE_BREAKERS)))
    return {"prompts": prompts}

@api_router.get("/chat/{match_id}/info")
async def get_chat_info(match_id: str, current_user: User = Depends(get_current_user)):
    """Get chat info including match details, extend status, streak"""
    match = await db.matches.find_one({"match_id": match_id}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    if current_user.user_id not in [match["user1_id"], match["user2_id"]]:
        raise HTTPException(status_code=403, detail="Not your match")
    
    other_id = match["user2_id"] if match["user1_id"] == current_user.user_id else match["user1_id"]
    other_profile = await db.dating_profiles.find_one({"user_id": other_id}, {"_id": 0})
    other_user = await db.users.find_one({"user_id": other_id}, {"_id": 0})
    
    # Calculate extends used and allowed
    extends_used = match.get("extends_used", 0)
    
    # Higher tier wins
    my_tier = current_user.subscription_tier
    other_tier = other_user.get("subscription_tier", "free") if other_user else "free"
    tier_priority = {"free": 0, "premium": 1, "elite": 2}
    effective_tier = my_tier if tier_priority.get(my_tier, 0) >= tier_priority.get(other_tier, 0) else other_tier
    extends_allowed = SUBSCRIPTION_PLANS.get(effective_tier, {}).get("extends_per_chat", 0)
    
    # Streak info
    streak = match.get("chat_streak", 0)
    
    # Time remaining
    now = datetime.now(timezone.utc)
    expires_at = match["expires_at"]
    time_remaining = (expires_at - now).total_seconds()
    hours_remaining = max(0, time_remaining / 3600)
    
    # Warning levels
    warning = None
    if time_remaining <= 600:  # 10 minutes
        warning = "critical"
    elif time_remaining <= 3600:  # 1 hour
        warning = "warning"
    
    # Unread count
    unread = await db.messages.count_documents({
        "match_id": match_id, "receiver_id": current_user.user_id, "read": False
    })
    
    # Last active (respect hide_last_seen)
    last_active = None
    other_settings = await db.user_settings.find_one({"user_id": other_id}, {"_id": 0})
    hide_last_seen = other_settings.get("hide_last_seen", False) if other_settings else False
    
    if not hide_last_seen and other_profile:
        last_active = other_profile.get("last_active")
    
    # Can view read receipts (premium/elite only)
    can_see_read_receipts = my_tier in ["premium", "elite"]
    
    return {
        "match": match,
        "profile": other_profile,
        "extends_used": extends_used,
        "extends_allowed": extends_allowed,
        "effective_tier": effective_tier,
        "chat_streak": streak,
        "hours_remaining": round(hours_remaining, 1),
        "warning": warning,
        "unread_count": unread,
        "last_active": last_active,
        "can_see_read_receipts": can_see_read_receipts
    }

# ==================== Extend Match ====================

@api_router.post("/dating/matches/{match_id}/extend")
async def extend_match(match_id: str, current_user: User = Depends(get_current_user)):
    """Extend a match by 24 hours"""
    match = await db.matches.find_one({"match_id": match_id}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    if current_user.user_id not in [match["user1_id"], match["user2_id"]]:
        raise HTTPException(status_code=403, detail="Not your match")
    
    # Get both users' tiers
    other_id = match["user2_id"] if match["user1_id"] == current_user.user_id else match["user1_id"]
    other_user = await db.users.find_one({"user_id": other_id}, {"_id": 0})
    
    my_tier = current_user.subscription_tier
    other_tier = other_user.get("subscription_tier", "free") if other_user else "free"
    
    # Higher tier wins
    tier_priority = {"free": 0, "premium": 1, "elite": 2}
    effective_tier = my_tier if tier_priority.get(my_tier, 0) >= tier_priority.get(other_tier, 0) else other_tier
    
    extends_allowed = SUBSCRIPTION_PLANS.get(effective_tier, {}).get("extends_per_chat", 0)
    extends_used = match.get("extends_used", 0)
    
    if extends_used >= extends_allowed:
        tier_names = {"free": "Free", "premium": "Premium", "elite": "Elite"}
        raise HTTPException(
            status_code=400, 
            detail=f"No extends remaining. {tier_names.get(effective_tier, 'Current')} tier allows {extends_allowed} extends."
        )
    
    # Extend by 24 hours
    new_expires = match["expires_at"] + timedelta(hours=24)
    
    await db.matches.update_one(
        {"match_id": match_id},
        {"$set": {"expires_at": new_expires}, "$inc": {"extends_used": 1}}
    )
    
    return {
        "message": "Match extended by 24 hours!",
        "new_expires_at": new_expires.isoformat(),
        "extends_used": extends_used + 1,
        "extends_allowed": extends_allowed
    }

# ==================== Safety Routes ====================

@api_router.post("/safety/block")
async def block_user(block_data: BlockUser, current_user: User = Depends(get_current_user)):
    """Block a user"""
    if block_data.blocked_user_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")
    
    existing = await db.blocks.find_one({
        "blocker_id": current_user.user_id,
        "blocked_id": block_data.blocked_user_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="User already blocked")
    
    block_doc = {
        "block_id": f"block_{uuid.uuid4().hex[:12]}",
        "blocker_id": current_user.user_id,
        "blocked_id": block_data.blocked_user_id,
        "created_at": datetime.now(timezone.utc)
    }
    await db.blocks.insert_one(block_doc)
    
    # Remove any existing matches between them
    await db.matches.update_many(
        {"$or": [
            {"user1_id": current_user.user_id, "user2_id": block_data.blocked_user_id},
            {"user1_id": block_data.blocked_user_id, "user2_id": current_user.user_id}
        ]},
        {"$set": {"status": "blocked"}}
    )
    
    return {"message": "User blocked successfully"}

@api_router.delete("/safety/unblock/{user_id}")
async def unblock_user(user_id: str, current_user: User = Depends(get_current_user)):
    """Unblock a user"""
    await db.blocks.delete_one({
        "blocker_id": current_user.user_id,
        "blocked_id": user_id
    })
    return {"message": "User unblocked"}

@api_router.get("/safety/blocked")
async def get_blocked_users(current_user: User = Depends(get_current_user)):
    """Get list of blocked users"""
    blocks = await db.blocks.find(
        {"blocker_id": current_user.user_id}, {"_id": 0}
    ).to_list(100)
    
    result = []
    for block in blocks:
        user = await db.users.find_one({"user_id": block["blocked_id"]}, {"_id": 0, "user_id": 1, "name": 1, "profile_photo": 1})
        if user:
            result.append({**block, "user": user})
    
    return result

@api_router.post("/safety/report")
async def report_user(report_data: ReportUser, current_user: User = Depends(get_current_user)):
    """Report a user"""
    valid_reasons = ["harassment", "fake_profile", "spam", "inappropriate", "underage", "other"]
    if report_data.reason not in valid_reasons:
        raise HTTPException(status_code=400, detail=f"Invalid reason. Must be one of: {', '.join(valid_reasons)}")
    
    report_doc = {
        "report_id": f"report_{uuid.uuid4().hex[:12]}",
        "reporter_id": current_user.user_id,
        "reported_user_id": report_data.reported_user_id,
        "reason": report_data.reason,
        "details": report_data.details,
        "status": "pending",
        "created_at": datetime.now(timezone.utc)
    }
    await db.reports.insert_one(report_doc)
    
    return {"message": "Report submitted. We'll review within 24 hours.", "report_id": report_doc["report_id"]}

# ==================== User Settings ====================

@api_router.get("/settings")
async def get_settings(current_user: User = Depends(get_current_user)):
    """Get user privacy/app settings"""
    settings = await db.user_settings.find_one({"user_id": current_user.user_id}, {"_id": 0})
    if not settings:
        settings = {
            "user_id": current_user.user_id,
            "hide_last_seen": False,
            "hide_phone": True,
            "notifications_enabled": True,
        }
        await db.user_settings.insert_one(settings)
        # Return the settings without _id
        return {
            "user_id": current_user.user_id,
            "hide_last_seen": False,
            "hide_phone": True,
            "notifications_enabled": True,
        }
    return settings

@api_router.put("/settings")
async def update_settings(settings: dict, current_user: User = Depends(get_current_user)):
    """Update user settings"""
    allowed_keys = ["hide_last_seen", "hide_phone", "notifications_enabled"]
    update = {k: v for k, v in settings.items() if k in allowed_keys}
    
    # Only premium/elite can hide last seen
    if "hide_last_seen" in update and update["hide_last_seen"]:
        if current_user.subscription_tier == "free":
            raise HTTPException(status_code=403, detail="Hide last seen is a Premium/Elite feature")
    
    await db.user_settings.update_one(
        {"user_id": current_user.user_id},
        {"$set": update},
        upsert=True
    )
    return {"message": "Settings updated"}

# ==================== Helper: Chat Streak ====================

async def update_chat_streak(match_id: str, user_id: str):
    """Track chat streak - 3 consecutive days = streak badge"""
    today = datetime.now(timezone.utc).date().isoformat()
    
    streak_key = f"{match_id}_{today}"
    existing = await db.chat_activity.find_one({"key": streak_key, "user_id": user_id})
    
    if not existing:
        await db.chat_activity.insert_one({
            "key": streak_key,
            "match_id": match_id,
            "user_id": user_id,
            "date": today,
            "created_at": datetime.now(timezone.utc)
        })
        
        # Count consecutive days
        match = await db.matches.find_one({"match_id": match_id}, {"_id": 0})
        if match:
            activities = await db.chat_activity.find(
                {"match_id": match_id, "user_id": user_id},
                {"_id": 0}
            ).sort("date", -1).to_list(10)
            
            streak = len(activities)
            await db.matches.update_one(
                {"match_id": match_id},
                {"$set": {"chat_streak": streak}}
            )

# ==================== Waitlist Routes ====================

@api_router.get("/waitlist/count")
async def get_waitlist_count():
    """Get waitlist count - public endpoint"""
    count = await db.waitlist.count_documents({})
    return {
        "count": count,
        "limit": WAITLIST_LIMIT,
        "spots_remaining": max(0, WAITLIST_LIMIT - count),
        "is_full": count >= WAITLIST_LIMIT
    }

@api_router.post("/waitlist/join")
async def join_waitlist(entry: WaitlistEntry, current_user: User = Depends(get_current_user)):
    """Join the dating waitlist"""
    # Check age
    if entry.age < 18:
        raise HTTPException(status_code=400, detail="You must be 18+ to join the dating waitlist")
    
    # Check if already on waitlist
    existing = await db.waitlist.find_one({"user_id": current_user.user_id})
    if existing:
        raise HTTPException(status_code=400, detail="You're already on the waitlist!")
    
    # Check spots
    count = await db.waitlist.count_documents({})
    if count >= WAITLIST_LIMIT:
        raise HTTPException(status_code=400, detail="Waitlist is full! Stay tuned for updates.")
    
    waitlist_doc = {
        "waitlist_id": f"wl_{uuid.uuid4().hex[:12]}",
        "user_id": current_user.user_id,
        "name": entry.name,
        "age": entry.age,
        "city": entry.city,
        "gender": entry.gender or "",
        "notify": True,
        "position": count + 1,
        "joined_at": datetime.now(timezone.utc)
    }
    await db.waitlist.insert_one(waitlist_doc)
    
    return {
        "message": "You're on the waitlist!",
        "position": count + 1,
        "spots_remaining": max(0, WAITLIST_LIMIT - count - 1)
    }

@api_router.get("/waitlist/status")
async def get_waitlist_status(current_user: User = Depends(get_current_user)):
    """Check if current user is on the waitlist"""
    entry = await db.waitlist.find_one({"user_id": current_user.user_id}, {"_id": 0})
    if entry:
        return {"on_waitlist": True, "position": entry.get("position", 0), "joined_at": entry.get("joined_at")}
    return {"on_waitlist": False}

@api_router.post("/waitlist/notify")
async def waitlist_notify(current_user: User = Depends(get_current_user)):
    """Toggle notify preference for user already on waitlist"""
    entry = await db.waitlist.find_one({"user_id": current_user.user_id})
    if not entry:
        raise HTTPException(status_code=404, detail="Not on waitlist yet. Join first!")
    
    current_notify = entry.get("notify", True)
    await db.waitlist.update_one(
        {"user_id": current_user.user_id},
        {"$set": {"notify": not current_notify}}
    )
    return {"notify": not current_notify, "message": f"Notifications {'enabled' if not current_notify else 'disabled'}"}

@api_router.get("/dating/locked-status")
async def get_dating_locked_status():
    """Check if dating feature is currently locked"""
    return {
        "locked": DATING_LOCKED,
        "message": "Heaven Gate is coming soon! Join the waitlist." if DATING_LOCKED else "Heaven Gate is open!",
        "waitlist_limit": WAITLIST_LIMIT
    }

@api_router.get("/")
async def root():
    return {"message": "LiveNow API", "version": "2.0", "features": ["social", "dating"]}

# ==================== Badges Routes ====================

BADGE_DEFINITIONS = {
    "3_day_active": {"name": "Early Bird", "description": "Active for 3 days", "icon": "flame", "color": "#E8B44C"},
    "7_day_streak": {"name": "Week Warrior", "description": "Active for 7 days straight", "icon": "star", "color": "#D4AF37"},
    "verified_regular": {"name": "Verified Regular", "description": "30 days active member", "icon": "shield-checkmark", "color": "#2E7D4A"},
    "first_match": {"name": "First Spark", "description": "Got your first match", "icon": "heart", "color": "#E85D75"},
    "vibe_checker": {"name": "Vibe Checker", "description": "Completed 5 vibe checks", "icon": "camera", "color": "#1F3D2B"},
    "social_butterfly": {"name": "Social Butterfly", "description": "Made 10 friends", "icon": "people", "color": "#6B8E23"},
    "5_posts": {"name": "Real One", "description": "Shared 5 real moments", "icon": "images", "color": "#D4AF37"},
}

@api_router.get("/badges/definitions")
async def get_badge_definitions():
    """Get all available badge definitions"""
    return {"badges": BADGE_DEFINITIONS}

@api_router.get("/badges/my")
async def get_my_badges(current_user: User = Depends(get_current_user)):
    """Get current user's badges with details"""
    user_badges = current_user.badges or []
    result = []
    for badge_id in user_badges:
        if badge_id in BADGE_DEFINITIONS:
            result.append({"id": badge_id, **BADGE_DEFINITIONS[badge_id]})
    return {"badges": result, "total_available": len(BADGE_DEFINITIONS)}

# ==================== Notification Slots Route ====================

@api_router.get("/notifications/all-slots")
async def get_all_notification_slots():
    """Get all 3 daily posting slot times for scheduling notifications"""
    return {
        "posting_slots": POSTING_SLOTS,
        "golden_hours": GOLDEN_HOURS,
        "messages": {
            "Morning": "Good morning! Share your real moment now!",
            "Afternoon": "Afternoon vibes! Capture what you're up to!",
            "Night": "Night owl? Share your evening moment!",
        },
        "golden_hour_messages": {
            "Morning Coffee": "Golden Hour is LIVE! Find your match over morning coffee",
            "Lunch Break": "Golden Hour is LIVE! Lunch break connections await",
            "Night Owl": "Golden Hour is LIVE! Night owl matches are here",
        }
    }

# ==================== Privacy & Legal Routes ====================

@api_router.get("/legal/privacy-policy")
async def get_privacy_policy():
    """Get privacy policy"""
    return {
        "title": "Privacy Policy",
        "last_updated": "2025-06-01",
        "sections": [
            {
                "heading": "Information We Collect",
                "content": "We collect information you provide when creating your account (email, name, profile photo) and dating profile (age, gender, interests, photos). We also collect usage data like post activity, matches, and app interactions."
            },
            {
                "heading": "How We Use Your Information",
                "content": "Your data is used to provide the LiveNow experience - matching you with compatible users, showing relevant profiles, tracking your activity for badges and unlock requirements, and sending notifications about posting windows and matches."
            },
            {
                "heading": "Data Sharing",
                "content": "We do not sell your personal data. Your dating profile is visible only to other verified dating users. Your posts are visible only to your friends. Photos are stored securely on Cloudinary."
            },
            {
                "heading": "Age Requirement",
                "content": "The dating feature (Heaven Gate) is restricted to users aged 18 and above. We verify age during dating profile creation. Users under 18 cannot access dating features."
            },
            {
                "heading": "Data Retention",
                "content": "Posts expire after 24 hours. Match data expires based on your subscription tier (24-48 hours). You can delete your account and all associated data at any time."
            },
            {
                "heading": "Your Rights",
                "content": "You can access, update, or delete your personal data at any time through the app settings. Contact us at privacy@livenow.app for data-related requests."
            }
        ]
    }

@api_router.get("/legal/terms")
async def get_terms_of_service():
    """Get terms of service"""
    return {
        "title": "Terms of Service",
        "last_updated": "2025-06-01",
        "sections": [
            {
                "heading": "Acceptance of Terms",
                "content": "By using LiveNow, you agree to these terms. If you don't agree, please don't use the app."
            },
            {
                "heading": "Eligibility",
                "content": "You must be at least 13 years old to use the social features. Dating features (Heaven Gate) require you to be 18 or older."
            },
            {
                "heading": "Account Responsibility",
                "content": "You are responsible for maintaining the security of your account. Do not share your credentials. Report any unauthorized access immediately."
            },
            {
                "heading": "Content Guidelines",
                "content": "Posts must be real, unedited moments. No nudity, violence, hate speech, or illegal content. Vibe check photos must be genuine selfies. Violation leads to account suspension."
            },
            {
                "heading": "Dating Rules",
                "content": "Be respectful in all interactions. Misrepresenting your age, identity, or intentions is prohibited. Harassment of any kind will result in immediate ban."
            },
            {
                "heading": "Subscriptions",
                "content": "Premium and Elite are paid subscriptions. Prices are in INR (Premium: Rs 499/month, Elite: Rs 999/month). Subscriptions auto-renew unless cancelled."
            }
        ]
    }

@api_router.get("/legal/community-guidelines")
async def get_community_guidelines():
    """Get community guidelines"""
    return {
        "title": "Community Guidelines",
        "last_updated": "2025-06-01",
        "rules": [
            {"icon": "heart", "title": "Be Real", "description": "Share genuine moments. No filters, no fakes. That's the LiveNow way."},
            {"icon": "shield-checkmark", "title": "Be Respectful", "description": "Treat everyone with dignity. No bullying, harassment, or hate speech."},
            {"icon": "eye-off", "title": "Protect Privacy", "description": "Don't screenshot or share others' posts without permission."},
            {"icon": "warning", "title": "Report Bad Behavior", "description": "If something feels wrong, report it. We take action within 24 hours."},
            {"icon": "person", "title": "Be Yourself", "description": "Use your real name and photos. Catfishing is an instant ban."},
            {"icon": "lock-closed", "title": "Keep It Safe", "description": "Never share personal info like addresses or financial details in chats."},
            {"icon": "happy", "title": "Spread Positivity", "description": "Build others up. This community thrives on genuine connections."},
        ]
    }

# ==================== DAILY SLOT ASSIGNMENT ====================
# Camera windows: Morning Brew (9-11 AM), Midday Moment (1-3 PM), Night Reflections (9-11 PM)
CAMERA_SLOTS = [
    {"id": "morning_brew", "label": "Morning Brew", "emoji": "☕", "start_hour": 9, "end_hour": 11},
    {"id": "midday_moment", "label": "Midday Moment", "emoji": "☀️", "start_hour": 13, "end_hour": 15},
    {"id": "night_reflections", "label": "Night Reflections", "emoji": "🌙", "start_hour": 21, "end_hour": 23},
]

CAPTURE_WINDOW_MINUTES = 10  # Only 10 minutes to capture

async def get_user_streak(user_id: str) -> dict:
    """Calculate user's consecutive posting streak"""
    today = datetime.now().date()
    streak = 0
    check_date = today - timedelta(days=1)  # Start from yesterday
    
    while True:
        date_str = check_date.strftime("%Y-%m-%d")
        posted = await db.posts.find_one({
            "user_id": user_id,
            "created_at": {
                "$gte": datetime.combine(check_date, datetime.min.time()),
                "$lt": datetime.combine(check_date + timedelta(days=1), datetime.min.time())
            }
        })
        if posted:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break
        if streak >= 365:
            break
    
    # Check if posted today too
    today_str = today.strftime("%Y-%m-%d")
    posted_today = await db.posts.find_one({
        "user_id": user_id,
        "created_at": {
            "$gte": datetime.combine(today, datetime.min.time()),
            "$lt": datetime.combine(today + timedelta(days=1), datetime.min.time())
        }
    })
    
    has_golden_streak = streak >= 7
    
    # Award badge if 7-day streak
    if has_golden_streak:
        existing_badge = await db.users.find_one({"user_id": user_id, "badges": "golden_streak"})
        if not existing_badge:
            await db.users.update_one({"user_id": user_id}, {"$addToSet": {"badges": "golden_streak"}})
    
    return {
        "current_streak": streak + (1 if posted_today else 0),
        "posted_today": bool(posted_today),
        "has_golden_streak_badge": has_golden_streak,
    }

def pick_random_window(slot):
    """Pick a random 10-min window within the slot's 2-hour range"""
    total_minutes = (slot["end_hour"] - slot["start_hour"]) * 60
    max_start = total_minutes - CAPTURE_WINDOW_MINUTES
    random_offset = random.randint(0, max_start)
    window_start_hour = slot["start_hour"] + (random_offset // 60)
    window_start_min = random_offset % 60
    # Calculate end
    end_offset = random_offset + CAPTURE_WINDOW_MINUTES
    window_end_hour = slot["start_hour"] + (end_offset // 60)
    window_end_min = end_offset % 60
    return window_start_hour, window_start_min, window_end_hour, window_end_min

@api_router.get("/camera/daily-slot")
async def get_daily_slot(current_user: User = Depends(get_current_user), tz_offset: int = 0):
    """Get today's assigned camera slot for the user. Randomly assigns one if not yet assigned.
    tz_offset: User's timezone offset in minutes from UTC (e.g., IST = 330, EST = -300)
    """
    user_id = current_user.user_id
    
    # Use user's local date (not server UTC date) for slot assignment
    from datetime import timedelta as td
    user_now = datetime.now(timezone.utc) + td(minutes=tz_offset)
    today_str = user_now.strftime("%Y-%m-%d")
    
    # Check if already assigned
    assignment = await db.daily_slots.find_one({"user_id": user_id, "date": today_str})
    
    if not assignment:
        # Randomly pick one slot and a specific 10-min window
        slot = random.choice(CAMERA_SLOTS)
        w_sh, w_sm, w_eh, w_em = pick_random_window(slot)
        assignment = {
            "user_id": user_id,
            "date": today_str,
            "slot_id": slot["id"],
            "slot_label": slot["label"],
            "slot_emoji": slot["emoji"],
            "start_hour": slot["start_hour"],
            "end_hour": slot["end_hour"],
            "window_start_hour": w_sh,
            "window_start_min": w_sm,
            "window_end_hour": w_eh,
            "window_end_min": w_em,
            "assigned_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.daily_slots.insert_one(assignment)
    
    # Calculate the precise 10-min window times
    w_sh = assignment.get("window_start_hour", assignment["start_hour"])
    w_sm = assignment.get("window_start_min", 0)
    w_eh = assignment.get("window_end_hour", assignment["start_hour"])
    w_em = assignment.get("window_end_min", CAPTURE_WINDOW_MINUTES)
    
    now = datetime.now()
    window_start = now.replace(hour=w_sh, minute=w_sm, second=0, microsecond=0)
    window_end = now.replace(hour=w_eh, minute=w_em, second=0, microsecond=0)
    
    is_open = window_start <= now < window_end
    
    if is_open:
        remaining_sec = max(0, int((window_end - now).total_seconds()))
        next_open_sec = 0
    elif now < window_start:
        next_open_sec = max(0, int((window_start - now).total_seconds()))
        remaining_sec = 0
    else:
        next_open_sec = -1  # Window passed
        remaining_sec = 0
    
    # Get user's posting streak
    streak = await get_user_streak(user_id)
    
    return {
        "slot_id": assignment["slot_id"],
        "slot_label": assignment["slot_label"],
        "slot_emoji": assignment["slot_emoji"],
        "start_hour": assignment["start_hour"],
        "end_hour": assignment["end_hour"],
        "window_start_hour": w_sh,
        "window_start_min": w_sm,
        "window_end_hour": w_eh,
        "window_end_min": w_em,
        "capture_window_minutes": CAPTURE_WINDOW_MINUTES,
        "is_open": is_open,
        "remaining_sec": remaining_sec,
        "next_open_sec": next_open_sec,
        "date": today_str,
        "streak": streak,
        "all_slots": CAMERA_SLOTS,
    }

@api_router.get("/camera/tomorrow-slot")
async def get_tomorrow_slot(current_user: User = Depends(get_current_user)):
    """Pre-assign and get tomorrow's slot (for notification purposes)."""
    user_id = current_user.user_id
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    assignment = await db.daily_slots.find_one({"user_id": user_id, "date": tomorrow})
    
    if not assignment:
        slot = random.choice(CAMERA_SLOTS)
        w_sh, w_sm, w_eh, w_em = pick_random_window(slot)
        assignment = {
            "user_id": user_id,
            "date": tomorrow,
            "slot_id": slot["id"],
            "slot_label": slot["label"],
            "slot_emoji": slot["emoji"],
            "start_hour": slot["start_hour"],
            "end_hour": slot["end_hour"],
            "window_start_hour": w_sh,
            "window_start_min": w_sm,
            "window_end_hour": w_eh,
            "window_end_min": w_em,
            "assigned_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.daily_slots.insert_one(assignment)
    
    return {
        "slot_id": assignment["slot_id"],
        "slot_label": assignment["slot_label"],
        "slot_emoji": assignment["slot_emoji"],
        "start_hour": assignment["start_hour"],
        "end_hour": assignment["end_hour"],
        "window_start_hour": assignment.get("window_start_hour", assignment["start_hour"]),
        "window_start_min": assignment.get("window_start_min", 0),
        "window_end_hour": assignment.get("window_end_hour", assignment["start_hour"]),
        "window_end_min": assignment.get("window_end_min", CAPTURE_WINDOW_MINUTES),
        "capture_window_minutes": CAPTURE_WINDOW_MINUTES,
        "date": tomorrow,
    }


# ==================== DATING PROFILE & OPT-OUT ====================

MAX_DATING_REACTIVATIONS = 2

@api_router.get("/dating/profile/me")
async def get_dating_profile(current_user: User = Depends(get_current_user)):
    """Get current user's dating profile"""
    profile = await db.dating_profiles.find_one({"user_id": current_user.user_id}, {"_id": 0})
    user_doc = await db.users.find_one({"user_id": current_user.user_id}, {"_id": 0})
    
    opted_out = user_doc.get("dating_opted_out", False)
    reactivation_count = user_doc.get("dating_reactivation_count", 0)
    
    return {
        "profile": profile,
        "is_complete": profile is not None and len(profile.get("photos", [])) >= 2,
        "dating_opted_out": opted_out,
        "reactivation_count": reactivation_count,
        "max_reactivations": MAX_DATING_REACTIVATIONS,
        "can_reactivate": opted_out and reactivation_count < MAX_DATING_REACTIVATIONS,
        "interest_options": INTEREST_OPTIONS,
        "looking_for_options": LOOKING_FOR_OPTIONS,
    }

@api_router.post("/dating/profile/create")
async def create_dating_profile(profile_data: DatingProfileCreate, current_user: User = Depends(get_current_user)):
    """Create or update dating profile"""
    user_id = current_user.user_id
    
    # Validation
    if profile_data.age < 18:
        raise HTTPException(status_code=400, detail="Must be 18 or older")
    if not profile_data.gender or profile_data.gender not in ("male", "female", "other"):
        raise HTTPException(status_code=400, detail="Invalid gender")
    if not profile_data.city or len(profile_data.city.strip()) < 2:
        raise HTTPException(status_code=400, detail="City is required")
    if len(profile_data.photos) < 2:
        raise HTTPException(status_code=400, detail="At least 2 photos required")
    if len(profile_data.photos) > 3:
        raise HTTPException(status_code=400, detail="Maximum 3 photos allowed")
    if not profile_data.bio or len(profile_data.bio.strip()) < 10:
        raise HTTPException(status_code=400, detail="Bio must be at least 10 characters")
    if len(profile_data.interests) < 1:
        raise HTTPException(status_code=400, detail="Select at least 1 interest")
    if profile_data.looking_for not in LOOKING_FOR_OPTIONS:
        raise HTTPException(status_code=400, detail="Invalid 'looking for' option")
    
    # Check for live photos — must be from posts in last 7 days
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_posts = await db.posts.find(
        {"user_id": user_id, "created_at": {"$gte": seven_days_ago}},
        {"_id": 0, "front_image_url": 1, "back_image_url": 1}
    ).to_list(20)
    
    valid_photo_urls = set()
    for post in recent_posts:
        valid_photo_urls.add(post.get("front_image_url", ""))
        valid_photo_urls.add(post.get("back_image_url", ""))
    
    # Verify at least 2 photos are from live moments
    live_count = sum(1 for p in profile_data.photos if p in valid_photo_urls)
    if live_count < 2:
        raise HTTPException(status_code=400, detail="At least 2 photos must be from your recent Live Moments (last 7 days)")
    
    profile_doc = {
        "user_id": user_id,
        "name": current_user.name,
        "age": profile_data.age,
        "gender": profile_data.gender,
        "city": profile_data.city.strip(),
        "bio": profile_data.bio.strip(),
        "photos": profile_data.photos,
        "interests": profile_data.interests,
        "looking_for": profile_data.looking_for,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "is_verified": False,
    }
    
    # Upsert — create or update
    await db.dating_profiles.update_one(
        {"user_id": user_id},
        {"$set": profile_doc},
        upsert=True
    )
    
    return {"message": "Dating profile saved!", "profile": profile_doc}

@api_router.get("/dating/my-photos")
async def get_my_recent_photos(current_user: User = Depends(get_current_user)):
    """Get user's recent live photos (last 7 days) for dating profile selection"""
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    posts = await db.posts.find(
        {"user_id": current_user.user_id, "created_at": {"$gte": seven_days_ago}},
        {"_id": 0, "front_image_url": 1, "back_image_url": 1, "created_at": 1, "slot_name": 1}
    ).sort("created_at", -1).to_list(20)
    
    photos = []
    for post in posts:
        if post.get("front_image_url"):
            photos.append({"url": post["front_image_url"], "type": "front", "date": post["created_at"].isoformat() if isinstance(post.get("created_at"), datetime) else ""})
        if post.get("back_image_url"):
            photos.append({"url": post["back_image_url"], "type": "back", "date": post["created_at"].isoformat() if isinstance(post.get("created_at"), datetime) else ""})
    
    return {"photos": photos[:7], "total": len(photos)}

@api_router.post("/dating/opt-out")
async def dating_opt_out(body: DatingOptOutRequest, current_user: User = Depends(get_current_user)):
    """Permanently opt out of dating. Heaven Gate will be hidden."""
    user_id = current_user.user_id
    user_doc = await db.users.find_one({"user_id": user_id})
    
    if user_doc.get("dating_opted_out", False):
        raise HTTPException(status_code=400, detail="Already opted out")
    
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "dating_opted_out": True,
            "dating_opted_out_at": datetime.now(timezone.utc),
            "dating_opt_out_reason": body.reason or "",
        }}
    )
    
    # Log
    await db.admin_logs.insert_one({
        "log_id": f"log_{uuid.uuid4().hex[:12]}",
        "admin_id": "system",
        "action": "dating_opt_out",
        "target_user_id": user_id,
        "timestamp": datetime.now(timezone.utc),
        "details": body.reason or "",
    })
    
    return {"message": "You have opted out of dating. Heaven Gate is now hidden.", "dating_opted_out": True}

@api_router.post("/dating/reactivate")
async def dating_reactivate(current_user: User = Depends(get_current_user)):
    """Request to reactivate dating. Max 2 times ever."""
    user_id = current_user.user_id
    user_doc = await db.users.find_one({"user_id": user_id})
    
    if not user_doc.get("dating_opted_out", False):
        raise HTTPException(status_code=400, detail="You haven't opted out")
    
    count = user_doc.get("dating_reactivation_count", 0)
    if count >= MAX_DATING_REACTIVATIONS:
        raise HTTPException(status_code=400, detail=f"You have used all {MAX_DATING_REACTIVATIONS} reactivation requests. This decision is permanent.")
    
    await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {"dating_opted_out": False, "dating_reactivated_at": datetime.now(timezone.utc)},
            "$inc": {"dating_reactivation_count": 1},
        }
    )
    
    remaining = MAX_DATING_REACTIVATIONS - count - 1
    
    return {
        "message": f"Dating reactivated! You have {remaining} reactivation(s) remaining.",
        "dating_opted_out": False,
        "reactivation_count": count + 1,
        "remaining_reactivations": remaining,
    }


# ==================== ADMIN PANEL ====================

ADMIN_EMAIL = "admin@joinlivenow.app"
ADMIN_PASSWORD = "LiveNow@Admin2026"

async def seed_admin():
    """Create admin user if it doesn't exist"""
    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if not existing:
        admin_doc = {
            "user_id": f"admin_{uuid.uuid4().hex[:12]}",
            "email": ADMIN_EMAIL,
            "name": "LiveNow Admin",
            "password_hash": hash_password(ADMIN_PASSWORD),
            "bio": "Admin",
            "profile_photo": "",
            "push_token": None,
            "created_at": datetime.now(timezone.utc),
            "post_count": 0,
            "days_active": 0,
            "dating_unlocked": False,
            "badges": [],
            "subscription_tier": "elite",
            "is_admin": True,
            "last_active_date": datetime.now(timezone.utc).date().isoformat()
        }
        await db.users.insert_one(admin_doc)
        logger.info("Admin user seeded successfully")
    else:
        # Ensure is_admin flag is set
        if not existing.get("is_admin"):
            await db.users.update_one({"email": ADMIN_EMAIL}, {"$set": {"is_admin": True}})
            logger.info("Admin flag updated")

async def get_admin_user(authorization: Optional[str] = Header(None)) -> User:
    """Dependency: verifies the user is admin"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ")[1]
    user_id = verify_jwt_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    if not user_doc.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return User(**user_doc)

# --- Admin Auth ---
@api_router.post("/admin/login")
async def admin_login(credentials: UserLogin):
    """Admin-specific login — validates is_admin flag"""
    user_doc = await db.users.find_one({"email": credentials.email}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(credentials.password, user_doc.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user_doc.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Not an admin account")
    token = create_jwt_token(user_doc["user_id"])
    return {"token": token, "user": {"user_id": user_doc["user_id"], "name": user_doc["name"], "email": user_doc["email"], "is_admin": True}}

# --- Admin Dashboard ---
@api_router.get("/admin/dashboard")
async def admin_dashboard(admin: User = Depends(get_admin_user)):
    """Overview stats for admin panel"""
    total_users = await db.users.count_documents({"is_admin": {"$ne": True}})
    waitlist_total = await db.waitlist.count_documents({})
    waitlist_approved = await db.waitlist.count_documents({"status": "approved"})
    waitlist_rejected = await db.waitlist.count_documents({"status": "rejected"})
    waitlist_pending = await db.waitlist.count_documents({"status": {"$nin": ["approved", "rejected"]}})
    total_posts = await db.posts.count_documents({})
    total_reports = await db.reports.count_documents({})
    total_matches = await db.matches.count_documents({})

    # Recent signups (last 7 days)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_signups = await db.users.count_documents({"created_at": {"$gte": week_ago}, "is_admin": {"$ne": True}})

    return {
        "total_users": total_users,
        "recent_signups_7d": recent_signups,
        "waitlist": {
            "total": waitlist_total,
            "pending": waitlist_pending,
            "approved": waitlist_approved,
            "rejected": waitlist_rejected,
            "limit": WAITLIST_LIMIT,
        },
        "total_posts": total_posts,
        "total_reports": total_reports,
        "total_matches": total_matches,
    }

# --- Admin Waitlist Management ---
@api_router.get("/admin/waitlist")
async def admin_get_waitlist(
    status: Optional[str] = None,
    admin: User = Depends(get_admin_user)
):
    """Get all waitlisted users. Optionally filter by status: pending, approved, rejected"""
    query = {}
    if status == "pending":
        query["status"] = {"$nin": ["approved", "rejected"]}
    elif status in ("approved", "rejected"):
        query["status"] = status

    entries = await db.waitlist.find(query, {"_id": 0}).sort("joined_at", -1).to_list(500)

    # Enrich with user data
    enriched = []
    for entry in entries:
        user_doc = await db.users.find_one({"user_id": entry["user_id"]}, {"_id": 0, "email": 1, "profile_photo": 1, "created_at": 1, "post_count": 1})
        enriched.append({
            **entry,
            "email": user_doc.get("email", "") if user_doc else "",
            "profile_photo": user_doc.get("profile_photo", "") if user_doc else "",
            "user_created_at": user_doc.get("created_at", "").isoformat() if user_doc and user_doc.get("created_at") else "",
            "post_count": user_doc.get("post_count", 0) if user_doc else 0,
            "status": entry.get("status", "pending"),
            "joined_at": entry["joined_at"].isoformat() if isinstance(entry.get("joined_at"), datetime) else str(entry.get("joined_at", "")),
        })

    return {"waitlist": enriched, "total": len(enriched)}

@api_router.post("/admin/waitlist/{user_id}/approve")
async def admin_approve_waitlist(user_id: str, admin: User = Depends(get_admin_user)):
    """Approve a user from the waitlist — unlocks Heaven Gate for them"""
    entry = await db.waitlist.find_one({"user_id": user_id})
    if not entry:
        raise HTTPException(status_code=404, detail="User not found on waitlist")

    if entry.get("status") == "approved":
        raise HTTPException(status_code=400, detail="User already approved")

    # Update waitlist status
    await db.waitlist.update_one(
        {"user_id": user_id},
        {"$set": {
            "status": "approved",
            "approved_at": datetime.now(timezone.utc),
            "approved_by": admin.user_id,
        }}
    )

    # Unlock dating for the user
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"dating_unlocked": True}}
    )

    # Log admin action
    await db.admin_logs.insert_one({
        "log_id": f"log_{uuid.uuid4().hex[:12]}",
        "admin_id": admin.user_id,
        "action": "waitlist_approve",
        "target_user_id": user_id,
        "timestamp": datetime.now(timezone.utc),
    })

    return {"message": f"User {user_id} approved. Heaven Gate unlocked!", "status": "approved"}

@api_router.post("/admin/waitlist/{user_id}/reject")
async def admin_reject_waitlist(user_id: str, admin: User = Depends(get_admin_user)):
    """Reject a user from the waitlist"""
    entry = await db.waitlist.find_one({"user_id": user_id})
    if not entry:
        raise HTTPException(status_code=404, detail="User not found on waitlist")

    if entry.get("status") == "rejected":
        raise HTTPException(status_code=400, detail="User already rejected")

    await db.waitlist.update_one(
        {"user_id": user_id},
        {"$set": {
            "status": "rejected",
            "rejected_at": datetime.now(timezone.utc),
            "rejected_by": admin.user_id,
        }}
    )

    await db.admin_logs.insert_one({
        "log_id": f"log_{uuid.uuid4().hex[:12]}",
        "admin_id": admin.user_id,
        "action": "waitlist_reject",
        "target_user_id": user_id,
        "timestamp": datetime.now(timezone.utc),
    })

    return {"message": f"User {user_id} rejected from waitlist", "status": "rejected"}

# --- Admin User Management ---
@api_router.get("/admin/users")
async def admin_get_users(admin: User = Depends(get_admin_user)):
    """List all users"""
    users = await db.users.find({"is_admin": {"$ne": True}}, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(500)
    # Convert datetimes to strings
    for u in users:
        if isinstance(u.get("created_at"), datetime):
            u["created_at"] = u["created_at"].isoformat()
    return {"users": users, "total": len(users)}

@api_router.post("/admin/users/{user_id}/ban")
async def admin_ban_user(user_id: str, admin: User = Depends(get_admin_user)):
    """Ban/suspend a user"""
    user_doc = await db.users.find_one({"user_id": user_id})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")
    if user_doc.get("is_admin"):
        raise HTTPException(status_code=400, detail="Cannot ban admin")

    is_banned = user_doc.get("is_banned", False)
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"is_banned": not is_banned}}
    )

    await db.admin_logs.insert_one({
        "log_id": f"log_{uuid.uuid4().hex[:12]}",
        "admin_id": admin.user_id,
        "action": "ban" if not is_banned else "unban",
        "target_user_id": user_id,
        "timestamp": datetime.now(timezone.utc),
    })

    return {"message": f"User {'banned' if not is_banned else 'unbanned'}", "is_banned": not is_banned}

# --- Admin Reports ---
@api_router.get("/admin/reports")
async def admin_get_reports(admin: User = Depends(get_admin_user)):
    """View all user reports"""
    reports = await db.reports.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    # Enrich with user names
    enriched = []
    for r in reports:
        reporter = await db.users.find_one({"user_id": r.get("reporter_id")}, {"_id": 0, "name": 1, "email": 1})
        reported = await db.users.find_one({"user_id": r.get("reported_user_id")}, {"_id": 0, "name": 1, "email": 1})
        enriched.append({
            **r,
            "reporter_name": reporter.get("name", "Unknown") if reporter else "Unknown",
            "reported_name": reported.get("name", "Unknown") if reported else "Unknown",
            "created_at": r["created_at"].isoformat() if isinstance(r.get("created_at"), datetime) else str(r.get("created_at", "")),
        })
    return {"reports": enriched, "total": len(enriched)}

# --- Admin Logs ---
@api_router.get("/admin/logs")
async def admin_get_logs(admin: User = Depends(get_admin_user)):
    """View admin activity logs"""
    logs = await db.admin_logs.find({}, {"_id": 0}).sort("timestamp", -1).to_list(100)
    for l in logs:
        if isinstance(l.get("timestamp"), datetime):
            l["timestamp"] = l["timestamp"].isoformat()
    return {"logs": logs, "total": len(logs)}

# ==================== Health Check ====================
@api_router.get("/health")
async def health_check():
    """Health check endpoint for deployment monitoring"""
    try:
        await client.admin.command('ping')
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    return {
        "status": "healthy",
        "service": "LiveNow API",
        "version": "2.0.0",
        "database": db_status,
    }

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Seed admin user on startup"""
    await seed_admin()

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
