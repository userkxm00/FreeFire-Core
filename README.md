# 🎮 ARAFAT-LIKE-UPDATED: الشرح والتوثيق الشامل للمشروع (النسخة المدمجة)

> **دليل توثيقي شامل وتفصيلي** تم تحديثه بعد إتمام عملية الدمج الكاملة بين **نظام اللايكات** و**مولد الحسابات (TSun)** بنجاح مع الحفاظ على الكود الأصلي في نسخة احتياطية آمنة.

---

## 📌 1. نظرة عامة على النظام المدمج (Unified System Overview)

أصبح المشروع الآن نظاماً متكاملاً (All-in-One Service):
1. **خادم REST API (Flask)**:
   - يدير طلبات زيادة اللايكات عبر `GET /like`.
   - محمي بمفتاح أمان `?key=@ARAFAT_FLEX`.
   - يتضمن ميزة **التوليد الذاتي عند النقص (Auto-Refill)**: إذا كانت التوكنات لأي سيرفر أقل من الحد المطلوب (مثلاً أقل من 5 توكنات)، يقوم الخادم تلقائياً باستدعاء المولد في الخلفية لتسجيل حسابات جديدة واستخراج توكناتها وتغذية السيرفر فوراً.
2. **محرك توليد التوكنات عند الطلب (`/generate`)**:
   - نقطة نهاية برمجية تمكنك من توليد 10 إلى 100 توكن لأي سيرفر بطلب بسيط:
     - توليد متزامن (مباشر) أو غير متزامن في الخلفية (`async=true`).
     - نقطة نهاية لمتابعة حالة التوليد: `/generate/status?job_id=...`.
3. **مراقبة التوكنات (`/tokens/status`)**:
   - نقطة نهاية لمعرفة رصيد التوكنات المتوفرة في جميع السيرفرات (BD, IND, BR, ME, ID, CIS, إلخ).
4. **جسر التكامل (`generator_bridge.py`)**:
   - وحدة برمجية وسيطة تربط بين خادم اللايكات ومحرك `TSun-FF-Guest-Generator-main` مع دعم صيغتي التوكن (`token` و `jwt_token`) بدون أي تعارض.
5. **النسخة الاحتياطية الآمنة (`_backup_clean/`)**:
   - نسخة احتياطية كاملة ونظيفة من جميع الملفات والأكواد الأصلية قبل الدمج لضمان عدم ضياع أي كود.

---

## 🗂️ 2. شجرة وهيكلة الملفات بعد الدمج

```text
ARAFAT-LIKE-UPDATED/
│
├── 📁 _backup_clean/               # 🛡️ نسخة احتياطية كاملة من المشروع الأصلي قبل التعديل
│
├── 📄 app.py                       # السيرفر الرئيسي للـ Like API (محدث بنقاط النهاية والتوليد التلقائي)
├── 📄 generator_bridge.py          # ⚡ الجسر البرمجي الرابط بين محرك TSun والـ API
├── 📄 index.py                     # نقطة دخول Vercel Serverless
├── 📄 wsgi.py                      # نقطة تشغيل WSGI للإنتاج
├── 📄 vercel.json                  # إعدادات النشر السحابي
├── 📄 requirements.txt             # متطلبات المشروع الموحدة (Flask, aiohttp, requests, crypto, protobuf, etc.)
│
├── 📦 ملفات التوكنات المباشرة:
│   ├── 📄 token_bd.json            # توكنات سيرفر بنغلاديش (BD)
│   ├── 📄 token_ind.json           # توكنات سيرفر الهند (IND)
│   └── 📄 token_br.json            # توكنات سيرفر البرازيل وأمريكا (BR / US / SAC)
│
├── 📦 Protobuf Modules (تشفير وفك حزم البيانات):
│   ├── 📄 like_pb2.py              # حزمة إرسال اللايك (UID + Region)
│   ├── 📄 uid_generator_pb2.py     # حزمة استعلام معلومات اللاعب
│   └── 📄 visit_count_pb2.py       # حزمة قراءة بيانات البروفايل (الاسم، المستوى، اللايكات)
│
└── 📁 TSun-FF-Guest-Generator-main/ # محرك التوليد وكشف الحسابات النادرة
    ├── 📁 config/settings.py       # الإعدادات العامة ومفاتيح Garena
    ├── 📁 core/ (api.py, crypto.py, generator.py)
    ├── 📁 features/ (rarity.py, couples.py)
    ├── 📁 storage/file_ops.py
    └── 📁 TSun-Studio/             # مجلد حفظ الحسابات والتوكنات والنادرة
```

---

## 🌐 3. واجهات وبرمجة الـ API (Endpoints Reference)

جميع الطلبات المحمية تتطلب تمرير المفتاح: `?key=@ARAFAT_FLEX` (أو المفتاح الذي تحدده في متغير البيئة `API_KEY`).

### 1) إرسال اللايكات مع التوليد الذاتي (`GET /like`)
* **الرابط:**
  ```text
  GET /like?uid=123456789&region=BD&key=@ARAFAT_FLEX
  ```
* **كيف يعمل:**
  1. يفحص توكنات السيرفر (`region`).
  2. إذا كان عدد التوكنات منخفضاً، يُشغّل التوليد التلقائي فوراً في الخلفية.
  3. يرسل طلبات متوازية (`aiohttp`) إلى سيرفر اللعبة الرسمي.
  4. يُرجع النتيجة بتنسيق JSON:
  ```json
  {
    "LikesGivenByAPI": 15,
    "LikesafterCommand": 215,
    "LikesbeforeCommand": 200,
    "PlayerNickname": "PlayerName",
    "Level": 55,
    "Region": "BD",
    "UID": 123456789,
    "status": 1,
    "tokens_used": 15,
    "daily_limit": 30,
    "used": 1,
    "remaining": 29
  }
  ```

---

### 2) توليد التوكنات عند الطلب (`GET` أو `POST /generate`)
* **الرابط (مباشر / Synchronous):**
  ```text
  GET /generate?region=BD&count=10&threads=3&key=@ARAFAT_FLEX
  ```
* **الرابط (في الخلفية / Asynchronous):**
  ```text
  GET /generate?region=BD&count=25&async=true&key=@ARAFAT_FLEX
  ```
* **الرد (في حالة async=true):**
  ```json
  {
    "status": "queued",
    "job_id": "job_BD_1730849200",
    "region": "BD",
    "target": 25,
    "check_status_url": "/generate/status?job_id=job_BD_1730849200&key=@ARAFAT_FLEX"
  }
  ```

---

### 3) فحص حالة مهمة التوليد (`GET /generate/status`)
* **الرابط:**
  ```text
  GET /generate/status?job_id=job_BD_1730849200&key=@ARAFAT_FLEX
  ```
* **الرد:**
  ```json
  {
    "job_id": "job_BD_1730849200",
    "region": "BD",
    "target": 25,
    "completed": 18,
    "status": "running",
    "start_time": "2026-11-05 15:45:00"
  }
  ```

---

### 4) فحص رصيد التوكنات بجميع السيرفرات (`GET /tokens/status`)
* **الرابط:**
  ```text
  GET /tokens/status?key=@ARAFAT_FLEX
  ```
* **الرد:**
  ```json
  {
    "regions": {
      "BD": { "valid_tokens": 25, "file": "token_bd.json" },
      "IND": { "valid_tokens": 10, "file": "token_ind.json" },
      "BR": { "valid_tokens": 5, "file": "token_br.json" },
      "ME": { "valid_tokens": 0, "file": "token_me.json" }
    },
    "total_tokens_across_all": 40
  }
  ```

---

### 5) فحص الحصة اليومية المتبقية (`GET /remain`)
* **الرابط:**
  ```text
  GET /remain
  ```
* **الرد:**
  ```json
  {
    "daily_limit": 30,
    "remaining": 29,
    "used": 1,
    "reset_info": "4:00 AM IST"
  }
  ```

---

## 🚀 4. طريقة التشغيل

### تشغيل السيرفر محلياً:
```powershell
py app.py
```
سيبدأ السيرفر فوراً على:
`http://127.0.0.1:5000`

---

## 🛡️ 5. الحماية وضمان سلامة الكود
* تم حفظ النسخة الأصلية بالكامل في مجلد: **`_backup_clean/`**.
* لم يتم حذف أي ملف من ملفات `TSun-FF-Guest-Generator-main`.
* تم دعم كلا المفتاحين (`token` و `jwt_token`) لضمان عدم حدوث أي خطأ في قراءة ملفات JSON.
