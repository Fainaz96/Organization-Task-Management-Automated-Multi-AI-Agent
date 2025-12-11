from fastapi import APIRouter, HTTPException, status,Depends
from sqlalchemy import select,join # validates data types 
from db import get_db_connection  # import database connection and table
from model.user_model import users, role
from schema.auth_schema import ChangePasswordRequest, ChangePasswordResponse, LoginRequest, LoginResponse, ResetPasswordRequest
from schema.auth_schema import ForgotPasswordRequest, ForgotPasswordResponse
from utils.db_helper import execute_query
from utils.email_utils import send_reset_email  # import this if in a separate file
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
import uuid
from passlib.exc import UnknownHashError

router = APIRouter()

class Token(BaseModel):
    access_token: str
    token_type: str

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

SECRET_KEY = os.environ.get("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
RESET_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
api_key_header_auth = APIKeyHeader(name="Authorization", auto_error=False)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user_id(token: str = Depends(api_key_header_auth)) -> str:
    """
    Decodes the JWT token to get the user ID.
    This is the dependency that will be used in protected endpoints.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        user_id: str = payload.get("user_id")
        
        if user_id is None:
            raise credentials_exception
            
    except JWTError:
        raise credentials_exception

    return user_id

# --- THIS IS THE NEW FUNCTION YOU NEED TO ADD ---
async def get_user_id_from_token(token: str) -> str:
    """
    Decodes the JWT token passed as a string to get the user ID.
    Used for authenticating WebSockets where dependency injection is not available.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials (invalid token)",
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return user_id
# ---------------------------------------------


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    try:
        # conn = get_db_connection()
        # if not conn:
        #     raise HTTPException(status_code=503, detail="Database connection is not available.")
        
        # cursor = conn.cursor(dictionary=True)
            
        # user_query = """
        #     SELECT
        #         u.user_id,
        #         u.username,
        #         u.password,
        #         r.role_id,
        #         r.role_name AS role,
        #         d.name AS department_name,
        #         d.database_id AS notion_database_id
        #     FROM Users u
        #     LEFT JOIN RoleUser ru ON u.user_id = ru.user_id
        #     LEFT JOIN Roles r ON ru.role_id = r.role_id
        #     LEFT JOIN DepartmentUser du ON u.user_id = du.user_id
        #     LEFT JOIN Departments d ON du.department_id = d.department_id
        #     WHERE u.email = %s;
        # """
        
        # cursor.execute(user_query, (request.email,))
        # user = cursor.fetchone()

        async for conn in get_db_connection():  # get AsyncSession
                user = await execute_query(
                                    conn,
                                    """
                                                    SELECT
                                                        u.user_id,
                                                        u.username,
                                                        u.password,
                                                        r.role_id,
                                                        r.role_name AS role,
                                                        d.name AS department_name,
                                                        d.database_id AS notion_database_id
                                                    FROM Users u
                                                    LEFT JOIN RoleUser ru ON u.user_id = ru.user_id
                                                    LEFT JOIN Roles r ON ru.role_id = r.role_id
                                                    LEFT JOIN DepartmentUser du ON u.user_id = du.user_id
                                                    LEFT JOIN Departments d ON du.department_id = d.department_id
                                                    WHERE u.email = :email;
                                    """,
                                    {"email":request.email},
                                    fetch_one=False
                )

        if not user:
            # email not found
            raise HTTPException(
                status_code=401,
                detail="Incorrect Email address"
            )
            # Verify password
        try:
            valid = pwd_context.verify(request.password, user["password"])
        except UnknownHashError:
            # fallback for plaintext passwords (legacy users)
            valid = (request.password == user["password"])

        if not valid:
            raise HTTPException(
                status_code=401,
                detail="Incorrect Password"
            )   
             
        print(user)
        permissions = []
        if user["role_id"]:
            # cursor = conn.cursor()
            # permission_query = """
            #     SELECT p.permission_name
            #     FROM Permissions p
            #     JOIN RolePermission rp ON p.permission_id = rp.permission_id
            #     WHERE rp.role_id = %s;
            # """
            # cursor.execute(permission_query, (user["role_id"],))
            # permissions = [row['permission_name'] for row in cursor.fetchall()]
            # cursor.close()
            async for conn in get_db_connection():  # get AsyncSession
                permission_list = await execute_query(
                                    conn,
                                    """
                                        SELECT p.permission_name
                                        FROM Permissions p
                                        JOIN RolePermission rp ON p.permission_id = rp.permission_id
                                        WHERE rp.role_id = :role_id;
                                    """,
                                    {"role_id":user["role_id"]},
                                    fetch_one=False
                )
            permissions = [row['permission_name'] for row in permission_list]
            token = create_access_token(
                data={
                    'user_id':user["user_id"],
                    "department_name":user["department_name"],
                    "notion_database_id":user["notion_database_id"],
                    "permissions":permissions,
                    "department_name":user["department_name"]
                    })
            decoded_payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    
            print("Token is valid and successfully decoded.")
            print(f"Decoded Payload:\n{decoded_payload}\n")

            # 4. Extract and interpret the 'exp' claim
            expiration_timestamp = decoded_payload['exp']

            expiration_datetime = datetime.fromtimestamp(expiration_timestamp, tz=timezone.utc)
            
            print(f"Expiration Time (UTC): {expiration_datetime.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
            # print(f"Expiration Timestamp (Unix): {expiration_timestamp}")

            return LoginResponse(
                statuscode=200,
                message="Login successful!",
                username=user["username"],
                role=user["role"],
                token=str(token),
            )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 



# --- THIS IS THE NEW FUNCTION YOU NEED TO ADD ---
# async def get_user_id_from_token(token: str) -> str:
#     """
#     Decodes the JWT token passed as a string to get the user ID.
#     Used for authenticating WebSockets where dependency injection is not available.
#     """
#     credentials_exception = HTTPException(
#         status_code=status.HTTP_401_UNAUTHORIZED,
#         detail="Could not validate credentials (invalid token)",
#     )
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         user_id: str = payload.get("user_id")
#         if user_id is None:
#             raise credentials_exception
#     except JWTError:
#         raise credentials_exception
#     return user_id
# # ---------------------------------------------



# @router.post("/forgot-password", response_model=ForgotPasswordResponse)
# async def forgot_password(request: ForgotPasswordRequest):
#     query = users.select().where(users.c.email == request.email)
#     conn = get_db_connection()
#     cursor = conn.cursor()
#     cursor.execute("SELECT * FROM users LIMIT 1")
#     user = cursor.fetchone() 

#     if user is None:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not registered")

#     send_reset_email(request.email)

#     return ForgotPasswordResponse(
#         statuscode=200,
#         message="Password reset instructions have been sent to your email."
#     )

def create_reset_token(email: str):
    expire = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": email, "exp": expire, "jti": str(uuid.uuid4())}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(request: ForgotPasswordRequest):
    # conn = get_db_connection()
    # cursor = conn.cursor()
    # cursor.execute("SELECT * FROM your_table LIMIT 1")
    # user = cursor.fetchone() 
    # cursor.close()
    async for conn in get_db_connection():  # get AsyncSession
                user = await execute_query(
                                    conn,
                                    """
                                      SELECT * FROM user LIMIT 1
                                    """,
                                    None,
                                    fetch_one=False
                )
    

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not registered")

    token = create_reset_token(request.email)
    reset_link = f"https://aca-signew-test-frontend.wonderfulsea-06576632.eastus.azurecontainerapps.io/resetpassword?token={token}"  # Next.js page

    # send email containing reset_link
    send_reset_email(request.email)

    return ForgotPasswordResponse(
        statuscode=200,
        message="Password reset instructions have been sent to your email."
    )

@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    try:
        payload = jwt.decode(request.token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=400, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    # hash password before saving
    from passlib.hash import bcrypt
    hashed_password = bcrypt.hash(request.new_password)

    # conn = get_db_connection()
    # cursor = conn.cursor()
    # cursor.execute("UPDATE users SET password=%s WHERE email=%s", (hashed_password, email))
    # conn.commit()
    async for conn in get_db_connection():  # get AsyncSession
        await execute_query(
                                    conn,
                                    """
                                      UPDATE users SET password=:password WHERE email=:email
                                    """,
                                    {"password":hashed_password,"email":email},
                                    fetch_one=False
        )

    return {"message": "Password has been reset successfully"}

@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    request: ChangePasswordRequest,
    user_id: str = Depends(get_current_user_id)
):
    # conn = get_db_connection()
    # if not conn:
    #     raise HTTPException(status_code=503, detail="Database connection is not available.")
    # cursor = conn.cursor(dictionary=True)

    # cursor.execute("SELECT password FROM users WHERE user_id = %s", (user_id,))
    # user = cursor.fetchone()
    # cursor.close()
    async for conn in get_db_connection():  # get AsyncSession
        user = await execute_query(
                                    conn,
                                    """
                                      SELECT password FROM users WHERE user_id =:user_id
                                    """,
                                    {"user_id":user_id},
                                    fetch_one=True
        )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db_password = user["password"]
    try:
        valid = pwd_context.verify(request.old_password, db_password)
    except UnknownHashError:
        valid = (request.old_password == db_password)

    if not valid:
        raise HTTPException(status_code=400, detail="Old password is incorrect")

    hashed_password = pwd_context.hash(request.new_password)
    # cursor = conn.cursor()
    # cursor.execute(
    #     "UPDATE Users SET password = %s WHERE user_id = %s",
    #     (hashed_password, user_id)
    # )
    # conn.commit()
    # cursor.close()
    async for conn in get_db_connection():  # get AsyncSession
        user = await execute_query(
                                    conn,
                                    """
                                      UPDATE Users SET password = :password WHERE user_id =:user_id
                                    """,
                                    {"password":hashed_password,"user_id":user_id},
                                    fetch_one=True
        )
    return ChangePasswordResponse(statuscode=200, message="Password changed successfully")
