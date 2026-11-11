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
# -- read as `l`. Two corrections against the original pattern: the bare `l`
# -- litre was missing (102 catalog names kept `unidad=""` because of it, C3 in
# -- odd/tasks/catalog-matching-normalization.md), and `m` was removed because it
# -- matched any stray metre-like token and no product in these chains is sold
# -- by the metre.
UNIDADES = ("kgs", "grs", "lts", "mls", "kg", "gr", "ml", "cc", "lt", "g", "l")


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
