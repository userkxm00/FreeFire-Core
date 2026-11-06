import asyncio
import sys
import app

async def main():
    uid = sys.argv[1] if len(sys.argv) > 1 else "12747380350"
    region = sys.argv[2].upper() if len(sys.argv) > 2 else "ME"

    print(f"\n=======================================================")
    print(f"🚀 بدء إرسال اللايكات لحساب Free Fire")
    print(f"🎯 UID المستهدف: {uid}")
    print(f"🌍 السيرفر/المنطقة: {region}")
    print(f"=======================================================\n")

    tokens = app.load_tokens(region, auto_refill=False)
    if not tokens:
        print(f"❌ لم يتم العثور على توكنات في ملف token_{region.lower()}.json!")
        return

    print(f"✅ تم تحميل {len(tokens)} حساباً جاهزاً للعمل.")

    first_token = app.get_token_str(tokens[0])
    encrypted_uid = app.enc(uid)

    print("\n[1/3] جلب بيانات الحساب المباشرة من خادم Garena...")
    before = app.make_request(encrypted_uid, region, first_token)
    if not before:
        print("❌ تعذر الاتصال بخادم اللعبة. تأكد من أن الحساب موجود في هذا السيرفر.")
        return

    nickname = before.AccountInfo.PlayerNickname
    level = before.AccountInfo.Levels
    likes_before = before.AccountInfo.Likes
    print("-------------------------------------------------------")
    print(f"👤 اسم اللاعب: {nickname}")
    print(f"⭐ المستوى:    {level}")
    print(f"❤️ اللايكات الحالية: {likes_before}")
    print("-------------------------------------------------------")

    url = app.get_like_url(region)
    print(f"\n[2/3] جاري إرسال الطلبات عبر الحسابات الـ {len(tokens)} إلى: {url} ...")
    
    results = await app.send_multiple_requests(uid, region, url)
    success = sum(1 for r in results if not isinstance(r, Exception)) if results else 0
    fail = len(results) - success if results else len(tokens)
    print(f"✅ تم تنفيذ كل طلبات الإرسال: {success} استجابة ناجحة (200 OK)، {fail} أخطاء.")

    print("\n[3/3] فحص الحساب مجدداً لمعرفة التحديث في العداد...")
    after = app.make_request(encrypted_uid, region, first_token)
    if after:
        likes_after = after.AccountInfo.Likes
        diff = likes_after - likes_before
        print("=======================================================")
        print(f"❤️ اللايكات قبل العملية:  {likes_before}")
        print(f"❤️ اللايكات بعد العملية:   {likes_after}")
        print(f"➕ الزيادة الفعلية:       +{diff}")
        print("=======================================================")
        if diff > 0:
            print(f"🎉 مبارك! تمت إضافة {diff} لايك لحسابك بنجاح!")
        else:
            print("ℹ️ قبل خادم جارينا جميع الطلبات (200 OK)، ولم يزد العداد لأن هذه الحسابات قد أرسلت لايكاً لهذا الحساب اليوم (قاعدة Free Fire: لايك واحد لكل حساب زائر كل 24 ساعة).")

if __name__ == "__main__":
    # Clean up temporary run script if exists
    import os
    if os.path.exists("run_send_likes.py"):
        try: os.remove("run_send_likes.py")
        except Exception: pass
    asyncio.run(main())
