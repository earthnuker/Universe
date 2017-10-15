import re
from dateutil.parser import parse
from vessel import Vessel,Forum,InvalidVesselException,engine,session
from tqdm import tqdm
import urllib.request
import codecs
program_to_jinja={
    "children count": "vessel.children|length",
    "children random":"(vessel.children|random).name",
    "children list":"('\n - '~(vessel.children|lformat('{full_name_with_id} by {owner.full_name_with_id}')|join('\n - ') ) ) if vessel.children",
    "paradise paradoxes":"('\n - '~(atlas|lformat('{full_name_with_id} by {owner.full_name_with_id}')|join('\n - ') ) ) if atlas",
    "paradise spells":"('\n - '~(spells|lformat('{full_name_with_id} by {owner.full_name_with_id}')|join('\n - ') ) ) if spells",
    "paradise tunnels":"('\n - '~(tunnels|lformat('{full_name_with_id} by {owner.full_name_with_id}')|join('\n - ') ) ) if tunnels",
    "paradise count":"universe|length",
    "siblings count":"vessel.siblings|length",
    "siblings random":"(vessel.siblings|random).name",
    "siblings list":"('\n - '~(vessel.siblings|lformat('{full_name_with_id} by {owner.full_name_with_id}')|join('\n - ') ) ) if vessel.siblings",
    "time day":"time.day",
    "time year":"time.year",
    "time month":"time.month",
    "time clock":"time.clock",
    "time date":"time.date",
    "time above":"time.above",
    "time below":"time.below",
    "vessel id":"vessel.id",
    "vessel name":"vessel.name",
    "vessel parent id":"vessel.parent.id",
    "vessel parent name":"vessel.parent.name",
    "vessel stem id":"vessel.stem.id",
    "vessel stem name":"vessel.stem.name",
    "vessel random id":"vessel.random.id",
    "vessel random name":"vessel.random.name",
    #"random":"",
}

def parse_memory_array(data):
    value_slices=[]
    for line in data.splitlines():
        if not line.strip():
            continue
        if line.startswith("~"):
            continue
        if line.startswith("@ "):
            line=line.strip("@ ")
            first_word=line.split()[0]
            line=line.replace(first_word,first_word+"  ")
            for match in re.finditer("(\w+)\s*",line):
                value_slices.append((match.groups()[0].lower(),list(match.span())))
            value_slices[-1][1][1]=None
            value_slices=dict(value_slices)
            for k,v in value_slices.items():
                value_slices[k]=slice(*v)
        else:
            data={}
            for k,v in value_slices.items():
                data[k]=line[v].strip()
            yield data
def to_jinja(code):
    #return code
    if code and ("((" in code) and ("))" in code):
        chunk=code.split("((")[1].split("))")[0].strip()
        if chunk in program_to_jinja:
            code=code.replace(chunk," {} ".format(program_to_jinja[chunk]))
            code=code.replace("((","<( ").replace("))"," )>")
    return code
Vessel.metadata.drop_all(engine)
Vessel.metadata.create_all(engine)
vessel_url="https://raw.githubusercontent.com/XXIIVV/vessel.paradise/master/memory/paradise.ma"
vessels=str(urllib.request.urlopen(vessel_url).read(),"utf-8")
dropped=0
print("Importing Vessels...")
for id_val,record in enumerate(tqdm(list(parse_memory_array(vessels)),ascii=True,disable=False)):
    record['id']=id_val
    state,parent,owner,created=record['code'].split("-")
    record['parent_id']=int(parent.lstrip("0") or "0")
    record['owner_id']=int(owner.lstrip("0") or "0")
    record['created_raw']=created.lstrip("0") or None
    if record['created_raw']:
        record['created_raw']=parse(record['created_raw'])
    state={attr:val=="1" for attr,val in zip(("locked","hidden","silent","tunnel"),state)}
    record.update(state)
    del record['code']
    record['raw_note']=record['note']
    del record['note']
    for k,v in record.items():
        if isinstance(v,str):
            record[k]=to_jinja(v)
    if not record['name']:
        record['name']="nullspace"
    try:
        orig_locked=record['locked']
        record['locked']=False
        Vessel(**record).locked=orig_locked
    except InvalidVesselException as e:
        dropped+=1
    """
    if " ".join([record['attr'],record['name']]).strip():
        Vessel(**record)
    else:
        dropped+=1
    """
Vessel.update()
for v in Vessel.universe:
    if v.parent is None:
        v.parent_id=0
Vessel.update()
print("Dropped {} Vessels".format(dropped))
dropped=0
print("Importing Forum...")
forum_url="https://raw.githubusercontent.com/XXIIVV/vessel.paradise/master/memory/forum.ma"
forum=str(urllib.request.urlopen(forum_url).read(),"utf-8")
for id_val,record in enumerate(tqdm(list(parse_memory_array(forum)),ascii=True)):
    record['from_id']=int(record['from'].lstrip("0") or "0")
    del record['from']
    record['host_id']=int(record['host'].lstrip("0")  or "0")
    del record['host']
    record['timestamp_raw']=record['timestamp'].lstrip("0") or None
    del record['timestamp']
    if record['timestamp_raw']:
        record['timestamp_raw']=parse(record['timestamp_raw'])
    record['id']=id_val
    try:
        Forum(**record)
    except AssertionError:
        dropped+=1
Forum.update()
print("Dropped {} Messages".format(dropped))