import re

def remove_duplicates_by_key(objects_list, key):
    unique_keys = set()
    new_objects_list = []

    for obj in objects_list:
        if obj[key] not in unique_keys:
            unique_keys.add(obj[key])
            new_objects_list.append(obj)

    return new_objects_list

# -- Unit set for the stored `unidad`. Longest variants first so `lts` is never
# -- read as `l`. The bare `l` litre was the real gap: 102 catalog names kept
# -- `unidad=""` because of it (C3 in
# -- odd/tasks/catalog-matching-normalization.md). `m` stays: matching cannot
# -- resolve it as a unit family, but dropping it changed how metre-length names
# -- are stored, which is out of scope here (review R3-001).
UNIDADES = ("kgs", "grs", "lts", "mls", "kg", "gr", "ml", "cc", "lt", "g",
           "m", "l")


def name_parse(name):
    patron_peso_volumen = (r"(\d+(?:[.,]\d+)?|X\d+)\s*"
                           r"(" + "|".join(UNIDADES) + r")\b")

    concatenated_result=''
    resultados = re.findall(patron_peso_volumen, name, re.IGNORECASE)
    if (resultados):
        # -- re.escape: a decimal quantity carries a literal dot
        name = re.sub(r"\b" + re.escape(resultados[0][0]) + r"\s*"
                      + re.escape(resultados[0][1]) + r"\b", "", name)
        name = re.sub(r",\s*,", ",", name)
        name = re.sub(r"\s{2,}", " ", name)
        
        name = name.strip()
        
        concatenated_result = ", ".join([f"{cantidad} {unidad}" for cantidad, unidad in resultados])
        
        
    # resultParsed = resultados.con
    return {"name": name, "unidad": concatenated_result}
