import re
D=str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩","01234567890123456789")
GM=[("جنوری",1),("جنورى",1),("فروری",2),("فبروری",2),("مارچ",3),("اپریل",4),("اپريل",4),("اپرېل",4),("مئی",5),("می",5),("جون",6),("جولائی",7),("جولای",7),("جولانی",7),("اگست",8),("آگست",8),("ستمبر",9),("استمبر",9),("سپتمبر",9),("اکتوبر",10),("اكتوبر",10),("نومبر",11),("نوامبر",11),("دسمبر",12),("دیسمبر",12)]
def parse(s):
    """(day, month, year_or_None) from a printed Gregorian date."""
    if not s: return None
    t=s.translate(D).replace("ي","ی").replace("ك","ک")
    m=None
    for name,n in sorted(GM,key=lambda x:-len(x[0])):
        if re.search(r"(^|[\s\d])"+name+r"($|[\s\d،,])",t): m=n; break
    dm=re.search(r"(\d{1,2})",t)
    day=int(dm.group(1)) if dm else (1 if re.search(r"(^|\s)(اول|یکم|غره)(\s|$)",t) else None)
    if not (m and day) or not 1<=day<=31: return None
    ym=re.search(r"(19\d\d)",t)
    return day,m,(int(ym.group(1)) if ym else None)
