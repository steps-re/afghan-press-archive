import re
D=str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يكى","01234567890123456789یکی")
MONTHS=[("محرم",1),("صفر",2),("ربیع الاول",3),("ربیع الثانی",4),("ربیع الآخر",4),("ربیع الاخر",4),("جمادی الاول",5),("جمادی الاولی",5),("جمادی الثانی",6),("جمادی الثانیه",6),("جمادی الآخر",6),("جمادی الاخر",6),("رجب",7),("شعبان",8),("رمضان",9),("شوال",10),("ذی القعده",11),("ذیقعده",11),("ذی القعد",11),("ذی الحجه",12),("ذیحجه",12),("ذی حجه",12)]
def parse(s):
    if not s: return None
    t=s.translate(D).replace("أ","ا").replace("إ","ا").replace("ى","ی").replace("ة","ه").replace("ۀ","ه").replace("ٔ","").replace("ي","ی")
    t=re.sub(r"\s+"," ",t)
    t2=t.replace("ثانی","الثانی") if "الثانی" not in t else t
    m=None
    for name,n in sorted(MONTHS,key=lambda x:-len(x[0])):
        if name in t or name in t2: m=n; break
    if not m: return None
    day=1 if re.search(r"(^|\s)(یکم|غره|غرهٔ|اول)\s",t+" ") else None
    dm=re.match(r"\s*(\d{1,2})\s",t)
    if dm: day=int(dm.group(1))
    ym=re.search(r"(13\d\d)",t)
    if not (day and ym and 1<=day<=30): return None
    return f"{ym.group(1)}-{m:02d}-{day:02d}"
