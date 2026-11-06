# 🎮 FreeFire-Core: خادم اللايكات ومولد الحسابات المتكامل

> **مستودع احترافي ونظيف** يجمع بين نظام زيادة لايكات فري فاير (Like API) ومحرك إدارة الحسابات والتوكنات، مع لوحة تحكم ويب تفاعلية، وتحقق صارم من المدخلات، واختبارات آلية، ومطابقة معايير الأمان.

---

## 📌 1. نظرة عامة (Overview)

المشروع عبارة عن منصة متكاملة:
1. **خادم REST API (Flask)**:
   - يدير طلبات زيادة اللايكات عبر `GET /like`.
   - محمي بمفتاح أمان يدعم:
     - Header: `X-API-Key: YOUR_KEY`
     - Header: `Authorization: Bearer YOUR_KEY`
     - Query: `?key=YOUR_KEY`
   - تحقق صارم من صحة معرف اللاعب (UID) وصيغة التوكنات (JWT Format).
   - عداد استخدام يومي محمي بـ Thread-Lock ومحفوظ باستمرار في `usage_state.json` مع إعادة تعيين تلقائية كل 24 ساعة.
2. **لوحة تحكم تفاعلية (Web Dashboard)**:
   - متاحة مباشرة عبر المتصفح على `http://127.0.0.1:5000/`.
   - واجهة داكنة متطورة تمكنك من إرسال اللايكات، لصق التوكنات وحفظها، ومتابعة رصيد كل سيرفر.
3. **محرك إدارة التوكنات والجسر (`generator_bridge.py`)**:
   - يدعم استخراج التوكنات، وحفظها تلقائياً بدون تعارض في المفاتيح (`token` و `jwt_token`).
   - تنظيف تلقائي للذاكرة (TTL) لمنع تسريب الذاكرة في المهام الطويلة.
4. **حزمة اختبارات آلية (`tests/test_suite.py`)**:
   - تغطي التحقق من الأمان، فك وتشفير الـ Protobuf، والمسارات البرمجية بنسبة نجاح 100%.

---

## 🗂️ 2. هيكلة الملفات

```text
FreeFire-Core/
│
├── 📄 app.py                       # السيرفر الرئيسي للـ Like API (مؤمّن ومحدّث)
├── 📄 generator_bridge.py          # الجسر البرمجي بين المولد والـ API
├── 📄 push_to_github.bat           # سكربت رفع التحديثات التلقائي لـ GitHub
├── 📄 index.py & wsgi.py           # نقاط تشغيل الإنتاج و WSGI
├── 📄 vercel.json                  # إعدادات النشر السحابي (Python 3.11 Runtime)
├── 📄 requirements.txt             # متطلبات المشروع بإصدارات محددة ومثبتة
├── 📄 usage_state.json             # ملف حفظ عداد الاستخدام اليومي المستمر
│
├── 📁 tests/                       # حزمة الاختبارات الآلية
│   └── 📄 test_suite.py            # اختبارات الوحدة والتحقق من الأمان
│
├── 📦 ملفات التوكنات:
│   ├── 📄 token_me.json            # سيرفر الشرق الأوسط (ME)
│   ├── 📄 token_bd.json            # سيرفر بنغلاديش (BD)
│   ├── 📄 token_ind.json           # سيرفر الهند (IND)
│   └── 📄 token_br.json            # سيرفر البرازيل وأمريكا (BR / US / SAC)
│
├── 📦 Protobuf Modules:
│   ├── 📄 like_pb2.py              # حزمة إرسال اللايك (UID + Region)
│   ├── 📄 uid_generator_pb2.py     # حزمة استعلام معلومات اللاعب
│   └── 📄 visit_count_pb2.py       # حزمة قراءة بيانات البروفايل (الاسم، المستوى، اللايكات)
│
└── 📁 TSun-FF-Guest-Generator-main/ # محرك التوليد وكشف الحسابات النادرة
```

> **ملاحظة بخصوص النسخة الاحتياطية:** مجلد النسخة الاحتياطية `_backup_clean/` محفوظ محلياً على جهاز المطور لضمان سلامة الكود، وهو مستثنى في `.gitignore` للحفاظ على نظافة وحجم المستودع العام على GitHub.

---

## 🌐 3. واجهات وبرمجة الـ API (Endpoints Reference)

### 1) إرسال اللايكات (`GET /like`)
* **الرابط:**
  ```text
  GET /like?uid=12747380350&region=ME
  Headers: X-API-Key: YOUR_KEY
  ```
* **التحقق:**
  - `uid`: يجب أن يكون رقماً بين 7 و 15 خانة.
  - `region`: يجب أن يكون من السيرفرات المعتمدة (ME, BD, IND, BR, SAC, ID, VN, TH, PK, CIS, SG, TW).

---

### 2) إضافة توكنات مباشرة (`POST /tokens/add`)
* **الرابط:**
  ```text
  POST /tokens/add
  Headers: X-API-Key: YOUR_KEY
  Content-Type: application/json
  ```
* **Body:**
  ```json
  {
    "region": "ME",
    "tokens": "eyJhbGciOiJIUzI1NiJ9..."
  }
  ```
* **التحقق:** يتم التحقق تلقائياً من بنية الـ JWT (ثلاثة أجزاء مفصولة بنقاط تبدأ بـ `ey`). أي نص عشوائي يُرفض فوراً بـ 400 Bad Request.

---

### 3) توليد التوكنات (`GET` أو `POST /generate`)
* **الرابط:**
  ```text
  POST /generate
  Headers: X-API-Key: YOUR_KEY
  Body: {"region": "ME", "count": 10, "async": true}
  ```
* **الأمان:** لا يتم تسريب مفتاح الـ API في رابط `check_status_url`.

---

### 4) فحص رصيد التوكنات (`GET /tokens/status`)
* **الرابط:**
  ```text
  GET /tokens/status
  Headers: X-API-Key: YOUR_KEY
  ```

---

### 5) فحص الحصة اليومية (`GET /remain`)
* **الرابط:**
  ```text
  GET /remain
  Headers: X-API-Key: YOUR_KEY
  ```

---

## 🧪 4. تشغيل الاختبارات الآلية (Running Unit Tests)

لتشغيل حزمة الاختبارات الآلية والتأكد من سلامة جميع المكونات:
```powershell
py tests/test_suite.py
```
النتيجة المتوقعة:
```text
...........
----------------------------------------------------------------------
Ran 11 tests in 0.038s

OK
```

---

## 🚀 5. تشغيل السيرفر

```powershell
py app.py
```
ثم افتح لوحة التحكم في المتصفح:
`http://127.0.0.1:5000`
