from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import sqlite3, os
from contextlib import contextmanager

BASE=os.path.dirname(__file__)
DB=os.getenv('CLINIC_DB',os.path.join(BASE,'clinic.db'))
app=FastAPI(title='Smart Clinic MVP')
app.mount('/static',StaticFiles(directory=os.path.join(BASE,'static')),name='static')

@contextmanager
def conn():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
 try: yield c;c.commit()
 finally:c.close()

def init():
 with conn() as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS patients(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,phone TEXT DEFAULT '',gender TEXT DEFAULT '',birth_year INTEGER,occupation TEXT DEFAULT '',country TEXT DEFAULT 'العراق',governorate TEXT DEFAULT '',area TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS visits(id INTEGER PRIMARY KEY AUTOINCREMENT,patient_id INTEGER NOT NULL REFERENCES patients(id),visit_type TEXT NOT NULL,visit_date TEXT NOT NULL,reason TEXT DEFAULT '',weight REAL,height REAL,waist REAL,notes TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS labs(id INTEGER PRIMARY KEY AUTOINCREMENT,patient_id INTEGER NOT NULL REFERENCES patients(id),visit_id INTEGER REFERENCES visits(id),test_name TEXT NOT NULL,value TEXT NOT NULL,unit TEXT DEFAULT '',reference_range TEXT DEFAULT '',test_date TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,category TEXT NOT NULL,form TEXT NOT NULL,unit TEXT NOT NULL,quantity REAL NOT NULL DEFAULT 0,price_iqd INTEGER NOT NULL DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY AUTOINCREMENT,patient_id INTEGER NOT NULL REFERENCES patients(id),visit_id INTEGER REFERENCES visits(id),mode TEXT NOT NULL,goal TEXT DEFAULT '',duration_days INTEGER NOT NULL DEFAULT 7,calories INTEGER,protein REAL,carbs REAL,fat REAL,fiber REAL,meals TEXT DEFAULT '',supplements TEXT DEFAULT '',herbs TEXT DEFAULT '',lifestyle TEXT DEFAULT '',status TEXT NOT NULL DEFAULT 'draft',version INTEGER NOT NULL DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS stock_movements(id INTEGER PRIMARY KEY AUTOINCREMENT,product_id INTEGER NOT NULL REFERENCES products(id),delta REAL NOT NULL,reason TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY AUTOINCREMENT,patient_id INTEGER REFERENCES patients(id),invoice_type TEXT NOT NULL CHECK(invoice_type IN ('consultation','product')),amount_iqd INTEGER NOT NULL,notes TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
  ''')
init()

class Patient(BaseModel):
 name:str;phone:str='';gender:str='';birth_year:Optional[int]=None;occupation:str='';country:str='العراق';governorate:str='';area:str=''
class Visit(BaseModel):
 patient_id:int;visit_type:str;visit_date:str;reason:str='';weight:Optional[float]=None;height:Optional[float]=None;waist:Optional[float]=None;notes:str=''
class Lab(BaseModel):
 patient_id:int;visit_id:Optional[int]=None;test_name:str;value:str;unit:str='';reference_range:str='';test_date:str
class Product(BaseModel):
 name:str;category:str;form:str;unit:str;quantity:float=0;price_iqd:int=0
class Plan(BaseModel):
 patient_id:int;visit_id:Optional[int]=None;mode:str='hybrid';goal:str='';duration_days:int=7;calories:Optional[int]=None;protein:Optional[float]=None;carbs:Optional[float]=None;fat:Optional[float]=None;fiber:Optional[float]=None;meals:str='';supplements:str='';herbs:str='';lifestyle:str=''
class Invoice(BaseModel):
 patient_id:Optional[int]=None;invoice_type:str;amount_iqd:int;notes:str=''
class Movement(BaseModel):
 delta:float;reason:str

def rows(sql,params=()):
 with conn() as c:return [dict(r) for r in c.execute(sql,params).fetchall()]
def insert(table,data):
 keys=list(data);marks=','.join('?' for _ in keys)
 with conn() as c:
  cur=c.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({marks})",tuple(data.values()))
  return {'id':cur.lastrowid}
def exists(table,id):
 if not rows(f'SELECT id FROM {table} WHERE id=?',(id,)):raise HTTPException(404,f'{table} not found')

@app.get('/')
def home():return FileResponse(os.path.join(BASE,'static','index.html'))
@app.get('/api/dashboard')
def dashboard():
 with conn() as c:
  def one(q):return c.execute(q).fetchone()[0]
  return {'patients':one('SELECT COUNT(*) FROM patients'),'visits':one('SELECT COUNT(*) FROM visits'),'plans':one('SELECT COUNT(*) FROM plans'),'products':one('SELECT COUNT(*) FROM products'),'consultations_iqd':one("SELECT COALESCE(SUM(amount_iqd),0) FROM invoices WHERE invoice_type='consultation'"),'sales_iqd':one("SELECT COALESCE(SUM(amount_iqd),0) FROM invoices WHERE invoice_type='product'")}
@app.get('/api/patients')
def patients():return rows('SELECT * FROM patients ORDER BY id DESC')
@app.post('/api/patients',status_code=201)
def add_patient(v:Patient):
 if not v.name.strip():raise HTTPException(400,'Name required')
 return insert('patients',v.model_dump())
@app.get('/api/patients/{id}')
def patient(id:int):
 exists('patients',id)
 return {'patient':rows('SELECT * FROM patients WHERE id=?',(id,))[0],'visits':rows('SELECT * FROM visits WHERE patient_id=? ORDER BY visit_date DESC,id DESC',(id,)),'labs':rows('SELECT * FROM labs WHERE patient_id=? ORDER BY test_date DESC,id DESC',(id,)),'plans':rows('SELECT * FROM plans WHERE patient_id=? ORDER BY id DESC',(id,))}
@app.post('/api/visits',status_code=201)
def add_visit(v:Visit):exists('patients',v.patient_id);return insert('visits',v.model_dump())
@app.post('/api/labs',status_code=201)
def add_lab(v:Lab):exists('patients',v.patient_id);return insert('labs',v.model_dump())
@app.get('/api/products')
def products():return rows('SELECT * FROM products ORDER BY id DESC')
@app.post('/api/products',status_code=201)
def add_product(v:Product):
 if v.quantity<0 or v.price_iqd<0:raise HTTPException(400,'Invalid quantity or price')
 return insert('products',v.model_dump())
@app.post('/api/products/{id}/movement',status_code=201)
def move(id:int,v:Movement):
 with conn() as c:
  p=c.execute('SELECT quantity FROM products WHERE id=?',(id,)).fetchone()
  if not p:raise HTTPException(404,'Product not found')
  if p[0]+v.delta<0:raise HTTPException(400,'Insufficient stock')
  c.execute('UPDATE products SET quantity=quantity+? WHERE id=?',(v.delta,id))
  c.execute('INSERT INTO stock_movements(product_id,delta,reason) VALUES(?,?,?)',(id,v.delta,v.reason))
 return {'ok':True}
@app.post('/api/plans',status_code=201)
def add_plan(v:Plan):
 exists('patients',v.patient_id)
 if v.mode not in ('auto','manual','hybrid'):raise HTTPException(400,'Invalid mode')
 if v.duration_days<1 or v.duration_days>365:raise HTTPException(400,'Invalid duration')
 return insert('plans',v.model_dump())
@app.post('/api/plans/{id}/approve')
def approve(id:int):
 # MVP intentionally prevents clinical approval until identity, review and safety checks are implemented.
 raise HTTPException(403,'Clinical approval disabled in demo; requires authentication and safety review workflow')
@app.get('/api/invoices')
def invoices():return rows('SELECT * FROM invoices ORDER BY id DESC')
@app.post('/api/invoices',status_code=201)
def add_invoice(v:Invoice):
 if v.invoice_type not in ('consultation','product') or v.amount_iqd<0:raise HTTPException(400,'Invalid invoice')
 if v.patient_id:exists('patients',v.patient_id)
 return insert('invoices',v.model_dump())
