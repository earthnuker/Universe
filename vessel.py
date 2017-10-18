from sqlalchemy import create_engine
from sqlalchemy.orm import relationship, backref, validates
from sqlalchemy.orm import sessionmaker,scoped_session
from sqlalchemy.schema import ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from datetime import datetime
import random
import jinja2
import os
from date_time import Clock
class InvalidVesselException(Exception):
    pass
class Ghost(object):
    def __init__(self):
        self.name="ghost"
        self.attr,self.note,self.program="","",""
        self.id,self.parent_id,self.owner_id=None,None,None
        self.parent,self.owner=self,self
        self.locked,self.hidden,self.silent,self.tunnel=False,False,False,False
        self.children,self.siblings,self.visible,self.owned=[],[],[],[]
        self.created=datetime.now()
        self.rating=0
    def __repr__(self):
        return "<Ghost Vessel>"

articles=["into","some","the","a","an","one","to","in"]
question_words=["are","is","does","who","what","where","when","how","why","which"]
def clean_vessel_name(value):
    for w in articles:
        value=value.replace(" {} ".format(w)," ")
    for w in articles:
        if value.startswith("{} ".format(w)):
            value=value[len(w)+1:]
    return value.strip()
def split_vessel_name(value):
    if value:
        *attr,name=clean_vessel_name(value).split()
        attr=" ".join(attr).strip()
        return attr,name
    return "",""
Base = declarative_base()
engine = create_engine('sqlite:///universe.db', echo=False)
session = scoped_session(sessionmaker(bind=engine))

class ClassProperty(property):
    def __get__(self, cls, owner):
        return self.fget.__get__(None, owner)()

class Forum(Base):
    __tablename__ = "forum"
    id = Column(Integer,primary_key=True)
    host_id = Column(Integer,ForeignKey('vessels.id'))
    from_id = Column(Integer,ForeignKey('vessels.id'))
    message = Column(String,nullable=False)
    timestamp_raw = Column(DateTime,nullable=True,default=datetime.now,)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        session.add(self)
    
    @validates("host_id")
    def validate_host_id(self,key,host_id):
        assert Vessel.exists(Vessel.id==host_id),"Container vessel for message does not exist"
        return host_id
    
    @validates("from_id")
    def validate_from_id(self,key,from_id):
        assert Vessel.exists(Vessel.id==from_id),"Source vessel for message does not exist"
        return from_id
    
    def commit(self):
        return session.commit()
    
    @classmethod
    def update(self):
        return session.commit()
    
    @classmethod
    def find(cls,*args,**kwargs):
        return session.query(cls).filter(*args,**kwargs)
    
    @property
    def from_vessel(self):
        return Vessel.get(self.from_id)
    
    @property
    def host_vessel(self):
        return Vessel.get(self.host_id)
    
    @property
    def timestamp(self):
        return Clock().to_str(self.timestamp_raw)
    
    @timestamp.setter
    def set_timestamp(self,value):
        self.timestamp_raw=value
    
    
    @property
    def dict(self):
        ret={c.name: getattr(self, c.name) for c in self.__table__.columns}
        ret['host_vessel']=self.host_vessel
        ret['from_vessel']=self.from_vessel
        ret['rendered']=self.str
        return ret
    
    def __repr__(self):
        return '<Message from {} in {}>'.format(self.from_vessel.full_name_with_id,self.host_vessel.full_name_with_id)
    
    @property
    def str(self):
        if not self.message:
            return None
        if self.message.startswith("me "):
            ret="[{}] The {} {}".format(self.timestamp,self.from_vessel.full_name_with_id,self.message[3:])
        elif self.message.split()[0].lower() in question_words:
            ret="[{}] The {} asked '{}?'".format(self.timestamp,self.from_vessel.full_name_with_id,self.message.rstrip('?'))
        elif self.message.endswith("?"):
            ret="[{}] The {} asked '{}?'".format(self.timestamp,self.from_vessel.full_name_with_id,self.message.rstrip('?'))
        elif self.message.endswith("!"):
            ret="[{}] The {} shouted '{}!'".format(self.timestamp,self.from_vessel.full_name_with_id,self.message.rstrip('!'))
        elif self.message.isnumeric():
            try:
                msg_vessel=Vessel.get(int(self.message))
            except:
                msg_vessel=None
            if msg_vessel:
                ret="[{}] The {} indicated the {}".format(self.timestamp,self.from_vessel.full_name_with_id,msg_vessel.full_name_with_id)
            else:
                ret="[{}] The {} said '{}.'".format(self.timestamp,self.from_vessel.full_name_with_id,self.message.rstrip('.'))
        else:
            ret="[{}] The {} said '{}.'".format(self.timestamp,self.from_vessel.full_name_with_id,self.message.rstrip('.'))
        return ret
        
class Vessel(Base):
    __tablename__ = "vessels"
    id = Column(Integer,primary_key=True)
    name = Column(String)
    attr = Column(String,default="")
    raw_note = Column(String,default="")
    program = Column(String,default="")
    
    parent_id = Column(Integer,ForeignKey('vessels.id'),default=None)
    _children_ = relationship("Vessel",primaryjoin =('Vessel.id == Vessel.parent_id'),backref=backref('parent', remote_side=[id]),post_update=True)
    owner_id = Column(Integer,ForeignKey('vessels.id'),default=None)
    owned = relationship("Vessel",primaryjoin =('Vessel.id == Vessel.owner_id'),backref=backref('owner', remote_side=[id]),post_update=True)
    created_raw = Column("created",DateTime,nullable=True,default=datetime.now)
    locked = Column(Boolean,default=False)
    hidden = Column(Boolean,default=False)
    silent = Column(Boolean,default=False)
    tunnel = Column(Boolean,default=False)
    
    def __init__(self,*args,**kwargs):
        if len(args)==1:
            attr,name=split_vessel_name(args[0])
            kwargs['name']=name
            kwargs['attr']=attr
            args=tuple()
        try:
            super().__init__(*args,**kwargs)
        except AssertionError as e:
            raise InvalidVesselException(*e.args)
        session.add(self)
    
    @validates('name','attr')
    def __check(self, key, value):
        if key=="attr" and value=="":
            return value
        assert 2<len(value)<16,"Vessel {} has to be between 3 and 15 characters".format(key.replace("attr","attribute"))
        return value
    
    @property
    def has_errors(self):
        checks=[
            (2<len(self.full_name)<30,"The vessel attribute and name has to be between 5 and 30 characters combined"),
        ]
        return [msg for c,msg in checks if not c]
    
    def commit(self):
        session.commit()
        if self.parent_id==None:
            self.parent_id=self.id
            session.commit()
        if self.owner_id==None:
            self.owner_id=self.parent_id
            session.commit()
    
    @property
    def created(self):
        return Clock().to_str(self.created_raw)
    
    @created.setter
    def set_created(self,value):
        self.created_raw=value
    
    @classmethod
    def update(self):
        return session.commit()
    
    @property
    def forum(self):
        if self.silent:
            return []
        return [r.dict for r in Forum.find(Forum.host_id==self.id).all()]
    
    @property
    def note(self):
        tagged=[]
        note=self.raw_note
        for vessel in self.find(Vessel.tunnel==True):
            if vessel.id in tagged:
                continue
            tagged.append(vessel.id)
            template="|{}|"
            if vessel.program:
                template="^"+template
            if len(vessel.full_name)>2:
                note=note.replace(vessel.full_name,template.format(vessel.full_name))
        for vessel in self.visible:
            if vessel.id in tagged:
                continue
            tagged.append(vessel.id)
            template="[{}]"
            if vessel.program:
                template="^"+template
            if len(vessel.full_name)>2:
                note=note.replace(vessel.full_name,template.format(vessel.full_name))
        return note
    
    @note.setter
    def set_note(self,value):
        self.raw_note=value
    
    @property
    def children(self):
        query=(
            (Vessel.parent_id==self.id) & \
            (Vessel.id != self.id) & \
            (Vessel.name!="")
        )
        if self.silent:
            return Vessel.find(query).filter((Vessel.owner_id == self.owner_id) | (Vessel.owner_id == self.id))
        else:
            return Vessel.find(query)
    
    @property
    def siblings(self):
        query=(
            (Vessel.parent_id==self.parent_id) & \
            (Vessel.id != self.parent_id) & \
            (Vessel.id != self.id) & \
            (Vessel.name!="")
        )
        if self.silent:
            return Vessel.find(query).filter((Vessel.owner_id == self.owner_id) | (Vessel.owner_id == self.id))
        else:
            return Vessel.find(query)
    
    @property
    def visible(self):
        ret=[]
        for v in self.siblings.all()+self.children.all():
            if v in ret:
                continue
            ret.append(v)
        return ret
    
    def find_visible(self,name):
        if not name:
            return None
        if name.isnumeric():
            name=int(name)
        tunnel_list=Vessel.find(Vessel.tunnel==True).all()
        tunnels=[]
        for tunnel in tunnel_list:
            if tunnel.full_name.strip():
                if self.raw_note.lower().find(tunnel.full_name.lower())!=-1:
                    tunnels.append(tunnel)
        if self.tunnel:
            tunnels+=Vessel.tunnels()
        visible=self.visible+tunnels
        if isinstance(name,int):
            for vessel in visible:
                if vessel.id==name:
                    return vessel
            return
        attr,name=split_vessel_name(name.lower())
        for vessel in visible:
            if vessel.name.lower()==name and vessel.attr.lower()==attr:
                return vessel
        for vessel in visible:
            if vessel.name.lower()==name:
                return vessel
        for vessel in visible:
            if vessel.attr.lower()==name:
                return vessel

    def find_child(self,name):
        if not name:
            return None
        children=self.children
        attr,name=split_vessel_name(name.lower())
        for vessel in children:
            if vessel.name.lower()==name and vessel.attr.lower()==attr:
                if vessel.parent.silent:
                    continue
                return vessel
        for vessel in children:
            if vessel.name.lower()==name:
                if vessel.parent.silent:
                    continue
                return vessel
        for vessel in children:
            if vessel.attr.lower()==name:
                return vessel

    @classmethod
    def find_random(cls):
        return cls.random()
    
    @classmethod
    def find_distant(cls,name):
        if not name:
            return None
        try:
            return cls.get(int(name))
        except ValueError:
            pass
        vessels=cls.find().all()
        attr,name=split_vessel_name(name.lower())
        for vessel in vessels:
            if vessel.name.lower()==name and vessel.attr.lower()==attr:
                return vessel
        for vessel in vessels:
            if vessel.name.lower()==name:
                return vessel
        for vessel in vessels:
            if vessel.attr.lower()==name:
                return vessel
    
    @classmethod
    def random(cls,*query_t,num=1):
        if not query_t:
            query_t=(Vessel,)
        cnt=session.query(Vessel).count()
        if not cnt:
            return Ghost()
        res=[]
        while len(res)!=num:
            id_n=random.choice(range(cnt))
            V=Vessel.get(id_n)
            if V is not None:
                res.append(V)
        if len(res)==1:
            return res[0]
        return res
    
    def random_child(self,num=1):
        if not self.children.count():
            return None
        res=random.sample(self.children.all(),num)
        if num==1:
            return res and res[0]
        return res
    
    def __repr__(self):
        return "<Vessel '{}' (ID: {})>".format("{} {}".format(self.attr,self.name).strip(),self.id)
    
    @property
    def cols(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
    
    @property
    def dict(self):
        cols=self.cols.copy()
        cols['parent']=self.parent
        cols['owner']=self.owner
        cols['children']=self.children.all()
        cols['num_children_']=len(cols['children'])
        cols['siblings']=self.siblings.all()
        cols['num_siblings']=len(cols['siblings'])
        cols['visible']=self.visible
        cols['num_visible']=len(cols['visible'])
        cols['stem']=self.stem
        cols['paradox']=self.paradox
        cols['depth']=self.depth
        cols['rating']=self.rating
        cols['full_name']=self.full_name
        cols['full_name_with_id']=self.full_name_with_id
        cols['random']=self.random()
        cols['random_child']=self.random_child()
        cols['forum']=self.forum
        return cols
    
    @property
    def full_name(self):
        return "{} {}".format(self.attr,self.name).strip()
    
    @property
    def full_name_with_id(self):
        return "{} (ID: {})".format(self.full_name,self.id)
    
    @property
    def rating(self):
        values=[
            self.note.strip()!="",
            self.attr.strip()!="",
            self.program.strip()!="",
            self.children.all(),
            self.paradox,
            self.locked,
            self.hidden,
            self.silent,
            self.tunnel,
        ]
        return int((sum(map(bool,values))/len(values))*100)
    
    def __getitem__(self,name):
        try:
            return self.dict[name]
        except KeyError as e:
            raise jinja2.exceptions.UndefinedError("'{}' is undefined".format(name))

    @classmethod
    def find(cls,*args,**kwargs):
        return session.query(cls).filter(*args,**kwargs)
    
    @classmethod
    def get(cls,id):
        try:
            return session.query(cls).get(id)
        except TypeError:
            return None
    
    @ClassProperty
    @classmethod
    def atlas(cls):
        ret=[]
        for vessel in cls.find(cls.id==cls.parent_id).all():
            if any([
                not vessel.locked,
                vessel.hidden,
                vessel.rating<50,
                vessel.id<1,
            ]):
                continue
            ret.append(vessel)
        return ret
    
    @ClassProperty
    @classmethod
    def tunnels(cls):
        ret=[]
        tunnel_list=cls.find(cls.tunnel==True).all()
        for vessel in cls.find(cls.hidden==False).filter(cls.locked==True).all():
            for tunnel in tunnel_list:
                if tunnel.full_name.strip():
                    if vessel.raw_note.lower().find(tunnel.full_name.lower())!=-1:
                        ret.append(vessel)
                        break
        return ret
    
    @ClassProperty
    @classmethod
    def spells(cls):
        return cls.find(cls.name=="spell").filter(cls.program!="").filter(cls.locked==True).filter(cls.attr!="").all()
    
    @ClassProperty
    @classmethod
    def universe(cls):
        return cls.find().all()
    
    
    @hybrid_property
    def paradox(self):
        return self.id==self.parent_id
    
    @property
    def stem(self):
        V=self
        L=[]
        while 1:
            L.append(V.id)
            if V.parent is None:
                break
            V=V.parent
            if V.parent_id==V.id:
                return V
            if V.id in L:
                return V
        return V
    
    def __setattr__(self,name,value):
        #print("Set",name,value)
        try:
            if name in self.dict:
                if self.locked and name!="locked":
                    print("The {} is locked and may not be modified".format(self.full_name_with_id))
                    return
        except AttributeError:
            pass
        return super().__setattr__(name,value)
    
    @property
    def depth(self):
        V=self
        L=[]
        d=0
        while 1:
            if V is None:
                break
            if V.id in L:
                break
            L.append(V.id)
            if V.parent_id==V.id:
                break
            V=V.parent
            d+=1
        return d
    
    @classmethod
    def exists(cls,*args,**kwargs):
        return session.query(session.query(cls).exists().where(*args,**kwargs)).scalar()