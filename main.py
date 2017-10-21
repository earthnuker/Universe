print("Loading...")
import os
import io
import sys
import cmd
import types
import base64
import codecs
import random
import textwrap
import readline
import argparse
import traceback
from functools import wraps,partial
from datetime import datetime,timedelta
import code
import importlib
try:
    import lupa # scripting
    import lupa._lupa # scripting
    has_lua=True
    LUA_LIMIT=1e8
    lua_whitelist=['assert','string','math',
                   'table','type','ipairs',
                   'error','tostring','unpack',
                   'print','setmetatable','getmetatable',
                   'select','tonumber','xpcall',
                   'module','pairs','pcall',
                   'next','inspect']
    lua_overrides={"string.rep":"""
    function(s,n)
        o=''
        for i=0,n do
            o=o..s
            if #o > 8192 then
                error('Maximum string length reached')
            end
        end
        return o
    end
    """}
    lua_blacklist=list(lua_overrides.keys())
    python_whitelist=['builtins','math','re','string','cmath','functools','time']
    python_blacklist=['time.sleep','builtins.quit','builtins.exit',
                      'builtins.globals','builtins.locals','builtins.eval','builtins.exec']
except ImportError:
    lua=None
    has_lua=False
import jinja2
import jinja2.meta
import jinja2.sandbox

from date_time import Clock
from vessel import Vessel,Ghost,Forum,InvalidVesselException
from vessel import split_vessel_name,clean_vessel_name,engine

#if not os.path.isfile("universe.db"):
#    import import_snapshot

class Cmd_Visitor(jinja2.visitor.NodeTransformer):
    def visit_Getattr(self,node):
        orig_lineno=node.lineno
        node=jinja2.nodes.Getitem(self.visit(node.node),jinja2.nodes.Const(node.attr),node.ctx)
        node=node.set_lineno(orig_lineno)
        return node

class Sandbox(jinja2.sandbox.ImmutableSandboxedEnvironment):
    intercepted_binops = frozenset(jinja2.sandbox.ImmutableSandboxedEnvironment.default_binop_table.keys())
    undefined = jinja2.StrictUndefined
    def call_binop(self, context, operator, left, right):
        if operator=='**':
            if abs(left)>1024 or right>1024:
                raise jinja2.exceptions.UndefinedError('use of the ** operator is restricted to numbers below 1024')
        return super().call_binop(context, operator, left, right)

def lformat(iterable, pattern="{}"):
    if iterable is None or isinstance(iterable, jinja2.Undefined):
        return iterable
    for value in iterable:
        if hasattr(value,"dict"):
            value=value.dict
        try:
            if isinstance(value,dict):
                yield pattern.format(**value)
            else:
                yield pattern.format(value)
        except:
            continue
jinja = Sandbox()
jinja.filters['lformat']=lformat

def eval_template(parser,cmd,vessel,target=None,recursive=False):
    if cmd.startswith("lua:"):
        cmd=bytes(cmd[4:],"utf-8")
        cmd=base64.b64decode(cmd)
        cmd=str(cmd,"utf-8")
        err,res=lua_eval(cmd,parser,target=target)
        if err:
            print("Error:",res)
        return None
    while 1:
        vessel=vessel or Ghost()
        old_cmd=cmd
        cmd=cmd.replace("{{","").replace("}}","")
        cmd=cmd.replace("{%","").replace("%}","")
        cmd=cmd.replace("##","").replace("##","")
        if "<(" in cmd and ")>" in cmd:
            cmd=cmd.replace("<(","{{ ").replace(")>"," }}")
        T_now=datetime.today()
        args={
            'vessel':vessel,
            'location':((lambda:parser.vessel.parent) if parser.vessel else (lambda:parser.location))(),
            'universe':Vessel.universe,
            'atlas':Vessel.atlas,
            'spells':Vessel.spells,
            'tunnels':Vessel.tunnels,
            'time':Clock().as_dict(),
            'nataniev':lambda tz:Clock(tz).as_dict(),
            'find':lambda id_n:Vessel.find_distant(id_n),
        }
        if target:
            args['target']=target
        try:
            template=jinja.parse(cmd)
        except:
            print(cmd)
            raise
        template=Cmd_Visitor().visit(template)
        template=template.set_environment(jinja)
        for var in jinja2.meta.find_undeclared_variables(template):
            if var not in args:
                raise jinja2.exceptions.UndefinedError("'{}' is undefined".format(var))
        cmd=jinja.from_string(template).render(args)
        if not recursive:
            return cmd
        if cmd==old_cmd:
            return cmd

def needs_vessel(func):
    @wraps(func)
    def wrapped(self,*args,**kwargs):
        if not self.vessel:
            print("You do not have a vessel.")
            print("You need to *create* something first and then *become* it")
            return
        return func(self,*args,**kwargs)
    wrapped.needs_vessel=True
    return wrapped

def modifies_vessel(func):
    func=needs_vessel(func)
    @wraps(func)
    def wrapped(self,*args,**kwargs):
        if self.vessel.parent.owner_id==self.vessel.id:
            self.vessel.parent.program=program
        else:
            print("You do not own the",self.vessel.parent.full_name)
            return
        return func(self,*args,**kwargs)
    wrapped.modifies_vessel=True
    return wrapped

class Cmd_Parser(cmd.Cmd):
    prompt="> "
    use_rawinput=True
    def __init__(self,location=None,*,test_mode=False):
        self.user_cmds=set()
        self.in_program = False
        self.vessel=None
        self.forum_size=5
        self.recursion_limit=50
        self.stack=[]
        if test_mode:
            self.visible_count=None
        else:
            self.visible_count=5
        if location is not None:
            if isinstance(location,Vessel):
                self.vessel=location
            else:
                self.location=Vessel.get(location)
        else:
            VL=Vessel.find().all()
            random.shuffle(VL)
            for self.location in VL:
                if any([
                    self.location.locked,
                    self.location.hidden,
                    self.location.rating<50,
                    self.location.id<1,
                    self.location.parent is None,
                    ]):
                    continue
                break
            else:
                print("No suitable Location found, picking a random one...")
                self.location=Vessel.random()
        self.test_mode=test_mode
        ret=super().__init__()
        if self.conninfo:
            print("[{}] Got connection from {}:{}".format(datetime.now(),*self.conninfo),file=sys.stderr)
        print("Universe v0.1")
        print()
        self.script("look",silent=True)
        if self.vessel:
            self.prev_loc=self.vessel.parent
        else:
            self.prev_loc=self.location
        return ret
    
    @property
    def conninfo(self):
        nc=(os.environ.get("NCAT_REMOTE_ADDR",None),os.environ.get("NCAT_REMOTE_PORT",None))
        ssh=os.environ.get("SSH_CONNECTION",None)
        if all(nc):
            return nc
        elif ssh:
            return tuple(ssh.split(" ")[:2])
    
    @property
    def netcat(self):
        return all((os.environ.get("NCAT_REMOTE_ADDR",None),os.environ.get("NCAT_REMOTE_PORT",None)))
    
    @property
    def ssh(self):
        return all(tuple(os.environ.get("SSH_CONNECTION",None).split(" ")[:2]))
    
    
    @property
    def prompt(self):
        prompt=""
        if self.vessel:
            prompt="{}@{}".format(self.vessel.id,self.vessel.parent_id)
            if self.vessel.paradox:
                prompt="{}".format(self.vessel.id,self.vessel.parent_id)
        elif self.location:
            prompt="(None)@{}".format(self.location.id)
        if self.in_program:
            prompt="(program|{})|{}".format(len(self.stack),prompt)
        return "[{}]> ".format(prompt)
    
    def cmdloop(self):
        self.cmdqueue.append("")
        return super(type(self),self).cmdloop(self.intro)
    
    def precmd(self,line):
        line=line.strip()
        if not line:
            return line
        Vessel.update()
        if self.conninfo:
            host,port=self.conninfo
            print("[{}] {}:{}|{}{}".format(datetime.now(),host,port,self.prompt,line),file=sys.stderr)
        cmd=line.split()[0]
        if cmd in ["program","note"]:
            return line
        try:
            return eval_template(self,line,self.vessel)
        except Exception as e:
            if self.test_mode:
                raise
            raise
            print("{}:".format(type(e).__name__),*e.args)
        return ''
    
    def postcmd(self,stop,line):
        Vessel.update()
        if not line:
            return
        if line.split()[0] in ["look","inspect","shell","help","print"]:
            print()
            return
        if getattr(getattr(self,"do_"+line.split()[0].lower(),None),"needs_vessel",None) is not None:
            if self.vessel is None:
                print()
                return
        if line.startswith("!") or line.split()[0]=="shell":
            print()
            return
        if stop:
            return super().postcmd(stop,line)
        if self.in_program:
            return
        if self.vessel:
            if self.prev_loc==self.vessel.parent:
                print()
                return
            self.prev_loc=self.vessel.parent
            article="your" if self.vessel.parent.owner_id==self.vessel.id else "the"
            paradox="Paradox" if self.vessel.parent.paradox else " "
            if self.vessel==self.vessel.parent:
                head="You are a paradox of {} {}".format(article,self.vessel.full_name_with_id).strip()
            else:
                head="You are the {} in {} {} {}".format(self.vessel.full_name_with_id,article,self.vessel.parent.full_name_with_id,paradox).strip()
            print()
            print(head)
            if self.vessel.parent.note.strip():
                print()
                print(eval_template(self,self.vessel.parent.note,self.vessel).strip())
            forum=self.vessel.parent.forum[-self.forum_size:]
            if forum and not line.strip().startswith("forum"):
                print()
                for message in forum:
                    msg=message['rendered']
                    if msg:
                        print(msg)
            visible=self.vessel.visible
            visible_short=visible[:self.visible_count]
            if visible:
                print()
                print("You can see:")
                for vessel in visible_short:
                    if vessel.parent_id==self.vessel.id:
                        continue
                    if not vessel.name:
                        continue
                    print(" -",vessel.full_name_with_id)
                if len(visible)>len(visible_short):
                    print("And {} more vessels (use *look* to see all)".format(len(visible)-len(visible_short)))
        elif self.location:
            if self.prev_loc==self.location:
                print()
                return
            self.prev_loc=self.location
            if self.location.paradox:
                print("You are a ghost in the {} Paradox".format(self.location.full_name_with_id))
            else:
                print("You are a ghost in the {}".format(self.location.full_name_with_id))
            if self.location.note.strip():
                print()
                print(eval_template(self,self.location.note,self.vessel or Ghost()).strip())
            forum=self.location.forum[-self.forum_size:]
            if forum and not line.strip().startswith("forum"):
                print()
                print("Last {} messages".format(self.forum_size))
                for message in forum:
                    msg=message['rendered']
                    if msg:
                        print(msg)
        print()
        return super().postcmd(stop,line)
    
    def emptyline(self):
        return
    
    def default(self,cmd):
        #TODO: check onbjects for do_{cmd} method, execute command
        return super(type(self),self).default(cmd)
    
    def script(self,*args,silent=False):
        self.stack.append(self.location)
        if len(self.stack)>self.recursion_limit:
            self.stack.clear()
            self.in_program=False
            raise Exception("Maximum recusion depth reached")
        self.in_program=True
        for line in args:
            if not silent:
                print("{}{}".format(self.prompt,line))
            line=self.precmd(line)
            stop=self.onecmd(line)
            stop=self.postcmd(stop,line)
        self.in_program=False
        self.stack.pop(-1)
    
    def do_rl(self,cmd):
        "Change readline configuration"
        return readline.parse_and_bind(cmd)
    
    def do_look(self,name):
        "Lists all visible Vessels."
        if name:
            print("Look takes no arguments")
            return
        if self.vessel:
            article="your" if self.vessel.parent.owner_id==self.vessel.id else "the"
            paradox="Paradox" if self.vessel.parent.paradox else " "
            if self.vessel==self.vessel.parent:
                head="You are a paradox of {} {}".format(article,self.vessel.full_name_with_id).strip()
            else:
                head="You are the {} in {} {} {}".format(self.vessel.full_name_with_id,article,self.vessel.parent.full_name_with_id,paradox).strip()
            print()
            print(head)
            if self.vessel.parent.note.strip():
                print()
                print(eval_template(self,self.vessel.parent.note,self.vessel).strip())
            visible=self.vessel.visible
            print()
            if not visible:
                print("You can see nothing")
                return
            print("You can see:")
            for vessel in visible:
                print(" -",vessel.full_name_with_id)
        else:
            if self.location.paradox:
                print("You are a ghost in the {} Paradox".format(self.location.full_name_with_id))
            else:
                print("You are a ghost in the {}".format(self.location.full_name_with_id))
            if self.location.note.strip():
                print()
                print(eval_template(self,self.location.note,self.vessel or Ghost()).strip())
            forum=self.location.forum[-self.forum_size:]
            if forum:
                print()
                print("Last {} messages".format(len(forum)))
                for message in forum:
                    print(message['rendered'])
            visible=self.location.children.all()
            print()
            if not visible:
                print("You can see nothing")
                return
            print("You can see:")
            for vessel in visible:
                print(" -",vessel.full_name_with_id)
    
    def do_forum(self,name):
        "Print message log"
        if name:
            print("forum takes no arguments")
            return
        if self.vessel:
            forum=self.vessel.parent.forum
        else:
            forum=self.location.forum
        if forum:
            print()
            for message in forum:
                print(message['rendered'])
        else:
            print("No messages")
    
    def do_inspect(self,name):
        "List details about a vessel."
        vessel=None
        if self.vessel:
            vessel=self.vessel.parent
            if name:
                vessel=self.vessel.find_visible(name)
        else:
            vessel=self.location
            if name:
                vessel=self.location.find_visible(name)
        if not vessel:
            vessel=Vessel.find_distant(name)
        if not vessel:
            print("Vessel {} could not be found".format(name))
            print()
            return
        print()
        print("The {}".format(vessel.full_name_with_id))
        print("="*len("The {}".format(vessel.full_name_with_id)))
        if vessel.owner:
            print("The {} is owned by the {}, has a rating of {}".format(vessel.full_name,vessel.owner.full_name_with_id,vessel.rating),end="")
        else:
            print("The {} is owned by nobody, has a rating of {}".format(vessel.full_name,vessel.rating),end="")
        if vessel.stem:
            if vessel.stem.id!=vessel.id:
                depth=vessel.depth
                if depth>1:
                    print(" and is currently {} levels deep within the {} paradox".format(vessel.depth,vessel.stem.full_name))
                else:
                    print(" and is currently {} level deep within the {} paradox".format(vessel.depth,vessel.stem.full_name))
            else:
                print(" and is a paradox".format(vessel.full_name))
            if vessel.stem.id!=vessel.id:
                print("Stem:",vessel.stem.full_name_with_id)
        if vessel.parent.id!=vessel.id:
            print("Parent:",vessel.parent.full_name_with_id)
        if vessel.note:
            print("Note:",repr(vessel.note))
        if vessel.program:
            print("Program:",repr(vessel.program))
        flags={
            "Hidden":vessel.hidden,
            "Silent":vessel.silent,
            "Tunnel":vessel.tunnel,
            "Locked":vessel.locked,
        }
        print("Flags:")
        for flag,value in sorted(flags.items()):
            print(" - {}: {}".format(flag,value))
        for n,sibling in enumerate(vessel.siblings):
            if not n:
                print("Siblings:")
            print(" -",sibling.full_name_with_id)
        for n,child in enumerate(vessel.children):
            if not n:
                print("Children:")
            print(" -",child.full_name_with_id)
        for n,visible in enumerate(vessel.visible):
            if not n:
                print("Visible:")
            print(" -",visible.full_name_with_id)
        for n,message in enumerate(vessel.forum):
            if not n:
                print("Forum:")
            print(" -",message['rendered'])
        print("="*len("the {}".format(vessel.full_name_with_id)))
        print()
    
    def do_create(self,name):
        "Create a new vessel at your current location."
        name = clean_vessel_name(name)
        if self.vessel:
            target=self.vessel.find_visible(name)
            if target:
                print("There is already a {} here".format(target.name))
                return
        else:
            target=self.location.find_child(name)
            if target:
                print("There is already a {} here".format(target.name))
                return
        try:
            V=Vessel(name)
        except InvalidVesselException as e:
            for err in e.args:
                print(err)
            return
        if self.vessel:
            V.owner_id=self.vessel.id
            V.parent_id=self.vessel.parent_id
        else:
            V.owner_id=self.location.id
            V.parent_id=self.location.id
        V.commit()
        print("Created a {}".format(V.full_name_with_id))
    
    def do_become(self,name):
        "Become a visible vessel, the target vessel must be present and visible in the current parent vessel."
        name=clean_vessel_name(name)
        if self.vessel:
            target=self.vessel.find_visible(name)
            if not target:
                print("There is no",name,"here")
                return
        else:
            target=self.location.find_visible(name)
            if not target:
                print("There is no",name,"here")
                return
        self.vessel=target
        print("You are now the {}".format(self.vessel.full_name_with_id))
    
    @needs_vessel
    def do_enter(self,name):
        "Enter a visible vessel."
        name = clean_vessel_name(name)
        target=self.vessel.parent.find_visible(name)
        if target:
            print("Entering the",target.full_name_with_id)
            self.vessel.parent_id=target.id
            self.vessel.update()
        else:
            print("There is no",name,"here")
    
    @needs_vessel
    def do_leave(self,name):
        "Exit the parent vessel."
        if name:
            print("Leave takes no arguments")
            return
        if self.vessel.parent.paradox:
            print("You cannot leave a Paradox")
            return
        print("Leaving the",self.vessel.parent.full_name_with_id,"and entering the ",self.vessel.parent.parent.full_name_with_id)
        self.vessel.parent_id=self.vessel.parent.parent_id
    
    @modifies_vessel
    def do_program(self,program):
        "Add an automation program to a vessel, making it available to the use command. ('help with programming' for more info)"
        self.vessel.parent.program=program
        
    @modifies_vessel
    def do_program_lua(self,args):
        "Add an automation program to a vessel, making it available to the use command. ('help with programming' for more info)"
        code=[]
        if args:
            code=[args]
        else:
            while 1:
                line=input("lua:>")
                if not line:
                    break
                code+=[line]
        code="\n".join(code)
        self.vessel.parent.program=str(b"lua:"+base64.b64encode(bytes(code,"utf-8")),"utf-8")
    
    @modifies_vessel
    def do_note(self,note):
        "Add a description to the current parent vessel."
        self.vessel.parent.raw_note=note
    
    @needs_vessel
    def do_fold(self,name):
        "Fold your vessel into itself, creating a paradox"
        if name:
            print("Fold takes no arguments")
            return
        self.vessel.parent_id=self.vessel.id
    
    @needs_vessel
    def do_warp(self,name):
        "Enter a distant vessel by either its name, or its warp id."
        name=clean_vessel_name(name)
        try:
            vessel=Vessel.get(int(name))
        except ValueError:
            vessel=self.vessel.find_visible(name)
            if not vessel:
                vessel=Vessel.find_distant(name)
        if not vessel:
            print("Target vessel not found")
            return
        if vessel.hidden:
            print("Target is hidden and may not be warped into")
            return
        print("Warping to {}".format(vessel.full_name_with_id))
        self.vessel.parent_id=vessel.id
    
    def do_print(self,name):
        "Prints its arguments, useful for messages or testing programs"
        if name:
            print(name)
    
    if not conninfo.fget(conninfo):
        def do_shell(self,cmd):
            "Evaluate python code or drop into an interactive shell"
            if not cmd:
                try:
                    code.interact(banner="Welcome to the debug console, don't break anything...",local=globals(),exitmsg="Bye!")
                except SystemExit:
                    print("Bye!")
                return
            try:
                print(eval(cmd,globals(),locals()))
            except Exception as e:
                traceback.print_exception(*sys.exc_info(),file=sys.stdout)
    
    def do_locate(self,name):
        "Locates a vessel by name"
        res=Vessel.find_distant(name)
        if res:
            print("Found",res.full_name_with_id)
            return
        print("{} not found".format(name))
    
    @modifies_vessel
    def do_set(self,name):
        """
        Directly write attributes for a owned vessel, the set command is meant to be used with programs and casted as spells.
        Attributes that can be set are:
         - locked: prevent modification to the vessel
         - hidden: prevent warping into the vessel
         - silent: prevent using the chat/forum in the vessel
         - tunnel: make the vessel accessible from other vessels notes
        """
        attr,value=name.split()
        if attr in ["is_{}".format(flag) for flag in ("locked","hidden","silent","tunnel")]:
            attr=attr[3:]
            if value.lower() in ["true","yes","1"]:
                value=True
            elif value.lower() in ["false","no","0"]:
                value=False
            else:
                print("Invalid value: {}".format(value))
                return
            if self.in_program:
                setattr(self.vessel,attr,value)
            else:
                setattr(self.vessel.parent,attr,value)
            return
        print("Invalid attribute: {}".format(attr))
    
    
    @needs_vessel
    def do_take(self,name):
        "Move a visible vessel into your current vessel."
        name = clean_vessel_name(name)
        target=self.vessel.find_visible(name)
        if target:
            if target.owner==self.vessel:
                target.parent_id=self.vessel.id
                print("You took the",target.full_name)
            else:
                print("You do not own",target.full_name)
        else:
            print("There is no",name,"here")
    
    @needs_vessel
    def do_drop(self,name):
        "Move a visible vessel out of your current vessel into your parent vessel."
        name = clean_vessel_name(name)
        target = self.vessel.find_child(name)
        if target:
            target.parent_id=self.vessel.parent_id
            print("You dropped the",target.full_name)
        else:
            print("You have no",name)

    @needs_vessel
    def do_use(self,name):
        "Execute a vessels program"
        name = clean_vessel_name(name)
        target=self.vessel.find_visible(name)
        if target:
            if not target.program:
                print("Target does not have a program")
                return
            command = eval_template(self,target.program,self.vessel)
            if not command:
                return
            self.in_program=True
            self.script(command)
            self.in_program=False
        else:
            print("There is no",name,"here")
    
    @needs_vessel
    def do_transform(self,name):
        "Change your current vessel's name and attribute"
        name = clean_vessel_name(name)
        attr,name=split_vessel_name(name)
        self.vessel.attr=attr
        self.vessel.name=name
    
    def do_lua_reset(self,args):
        """Reset lua environment"""
        global lua,lua_globals
        if args:
            print("lua_reset takes no arguments")
            return
        lua,lua_globals=init_lua()
        print("Lua Environment reset!")
    
    def do_lua(self,args):
        """Execute Lua code"""
        if not args:
            print("use '.exit' to exit lua-mode")
            print("use '.end' to end multiline input and eval code")
        while True:
            code=[]
            if args:
                code=[args]
            else:
                code=list(self.read_multiline("lua:>"))
            if not code:
                continue
            if code[-1]=='.exit':
                break
            code_s="\n".join(code)
            err,res=lua_eval(code_s,self)
            if err:
                print("Error:",res)
            else:
                if lupa.lua_type(res)=="table":
                    res=dict(res)
                print("Result:",res)
            if args: break
    
    def do_new_cmd(self,cmd):
        "Defines a new parser command"
        if not cmd:
            print("You need to supply a command to define")
            return
        print("use '.end' to end multiline input")
        code=list(self.read_multiline("cmd:{}:>".format(cmd)))
        code_s="\n".join(code)
        err,res=lua_eval(code_s,self)
        if err:
            print("Error:",res)
            return
        if not res:
            res=dict(lua_globals).get('do_'+cmd,None)
        if not lupa.lua_type(res)=='function':
            print("Error: lua code should return or define a function 'do_"+cmd+"'")
            return
        self.register_command(cmd,res)
        return
    
    def do_doc_cmd(self,cmd):
        "Document a user defined command"
        cmd_name="do_"+cmd
        if not hasattr(self,cmd_name):
            print("Can't document non-existing function!")
            return
        if not cmd_name in self.user_cmds:
            print("Can't document non-user-defined function!")
            return
        print("use '.end' to end multiline input")
        doc=list(self.read_multiline("doc:{}:>".format(cmd)))
        doc="\n".join(doc)
        self.document_command(cmd,doc)
        return
    
    def read_multiline(self,prompt):
        print(prompt,end="",flush=True)
        for line in sys.stdin:
            line=line.strip()
            if line==".end":
                break
            yield line
            if line==".exit":
                break
            print(prompt,end="",flush=True)
    
    @needs_vessel
    def do_cast(self,name):
        "Remotely execute a program, optionally in the context of another vessel (using 'cast ... onto ...')"
        for sep_ in ["on","onto"]:
            sep=" {} ".format(sep_)
            if sep in name:
                spell,target_name=map(clean_vessel_name,name.split(sep))
                target=self.vessel.find_visible(target_name)
                break
        else:
            spell=clean_vessel_name(name)
            target_name=self.vessel.full_name
            target=self.vessel
        try:
            spell_program=next(filter(lambda vessel:vessel.full_name==spell,Vessel.spells)).program
            if not spell_program.strip():
                print("Spell vessel does not have a program associated with it")
                return
            spell_command=eval_template(self,spell_program,self.vessel,target)
        except StopIteration:
            print("The {} does not exist".format(spell))
            return
        if not target:
            print("Target {} does not exist".format(target_name))
            return
        if spell_command!=spell_program:
            print("casting the {} ({} -> {}) onto the {}".format(spell,spell_program,spell_command,target.full_name_with_id))
        else:
            print("casting the {} ({}) onto the {}".format(spell,spell_command,target.full_name_with_id))
        if (spell_command.startswith("!") or spell_command.startswith("shell")) and hasattr(self,"do_shell"):
            print("Spells cannot evaluate python code")
            return
        if self.vessel:
            vessel_id=self.vessel.id
        else:
            vessel_id=None
        locked=target.locked
        target.locked=False
        owner_changed=False
        if target.owner.id==self.vessel.id:
            target.owner_id=target.id
            owner_changed=True
        target.locked=locked
        self.vessel=target
        self.in_program=True
        self.script(spell_command)
        self.in_program=False
        self.vessel=Vessel.get(vessel_id)
        locked=target.locked
        target.locked=False
        if owner_changed:
            target.owner_id=self.vessel.id
        target.locked=locked
    
    @needs_vessel
    def do_say(self,message):
        "Add a message into the global dialog."
        if self.vessel.parent.silent:
            print("The {} is silent, you may not talk here",format(self.vessel.parent.full_name))
            return
        message=message.strip()
        if message:
            msg=Forum(host_id=self.vessel.parent.id,from_id=self.vessel.id,message=message)
            print(msg.str)
        return
    
    @needs_vessel
    def do_signal(self,name):
        "Broadcast your current visible parent vessel."
        if self.vessel.parent.silent:
            print("The {} is silent, you may not talk here".format(self.vessel.parent.full_name))
            return
        name=name.strip().title()
        if name.isnumeric():
            if not Vessel.get(int(name)):
                print("Target vessel does not exist")
                return
            if Vessel.get(int(name)).hidden:
                print("The {} is hidden".format(Vessel.get(int(name)).full_name))
                return
            msg=Forum(host_id=self.vessel.parent.id,from_id=self.vessel.id,message=name)
        elif name:
            vessel=Vessel.find_distant(name)
            if vessel.hidden:
                print("The {} is hidden".format(vessel.full_name))
                return
            if vessel:
                msg=Forum(host_id=self.vessel.parent.id,from_id=self.vessel.id,message=str(vessel.id))
            else:
                print("Invalid argument")
                return
        else:
            msg=Forum(host_id=self.vessel.parent.id,from_id=self.vessel.id,message=str(self.vessel.parent.id))
        print(msg.str)
    
    @needs_vessel
    def do_emote(self,message):
        "Add an emote message into the global dialog."
        if self.vessel.parent.silent:
            print("The {} is silent, you may not talk here",format(self.vessel.parent.full_name))
            return
        if message:
            message="me "+message.strip()
            msg=Forum(host_id=self.vessel.parent.id,from_id=self.vessel.id,message=message)
            print(msg.str)
        return
    
    def get_names(self):
        user_cmds=[c[3:] for c in self.user_cmds]
        ret=[]
        for cmd in dir(self):
            if cmd.startswith(("do_","help_")):
                if cmd.split("_",1)[1] not in user_cmds:
                    ret.append(cmd)
        return ret
    
    def do_help(self,name):
        "Prints help."
        if name:
            if name.startswith("with "):
                name=name.replace("with ","")
            return super().do_help(name)
        super().do_help(name)
        user_cmds_doc=[]
        user_cmds_undoc=[]
        for cmd in sorted(self.user_cmds):
            cmd_name=cmd[3:]
            if hasattr(self,"help_"+cmd_name):
                user_cmds_doc.append(cmd_name)
            else:
                user_cmds_undoc.append(cmd_name)
        self.print_topics("Documented user defined commands",user_cmds_doc, 15,80)
        self.print_topics("Undocumented user defined commands",user_cmds_undoc, 15,80)

    def help_wildcards(self):
        print(textwrap.dedent("""
        Wildcards are dynamic text to be used in notes and programs to create responsive narratives.
        
        Wildcards get evaluated as Jinja2 Templates with the following Variables defined:
        
        'vessel': your current vessel,
        'universe': a list of all existing vessels,
        'atlas': a list of all paradoxes,
        'spells': a list of all vessels that can be cast as spells,
        'tunnels': a list of all tunnel vessels,
        'time': the current time and date in the nataniev time-system (http://wiki.xxiivv.com/Clock),
        'nataniev': a function for retrieving the nataniev time and date for a different timezone,
        'find': function for locating vessels by name or ID,
        'target': target of a spell program (only defined when casting a spell)
        
        Examples:
            <(vessel.name)> # return the name of the current vessel
            <(vessel.id)> # return the id of the current vessel
            <(vessel.parent.name)> # return the name of the current vessel's parent vessel
            <(vessel.parent.id)> # return the id of the current vessel's parrent vessel
            <(find('residences').children|map(attribute='full_name')|join('\\n'))> # locates the first vessel named 'residences' and returns a newline-separated list of it's child vessel's full names
        """).lstrip())
    
    def help_spells(self):
        print(textwrap.dedent("""
        Spells are programs that can be activated from any location by using the 'cast' command.
        A spell vessel needs to be programmed, locked, and have the '<something> spell' name format to qualify.
        Once a spell has been crafted, it can be used with the cast action, from anywhere, by all players.
        Spells can also be cast onto other vessels which makes their program execute in the context of the vessel the spell is cast onto.
        """).lstrip())
    
    def help_movement(self):
        print(textwrap.dedent("""
        Movement is quite simple:
         - Use 'enter <vessel name>' to move your current vessel into another vessel
         - Use 'leave' to move your current vessel out of it's current location and into the parent vessel
        """).lstrip())
    
    def help_communication(self):
        print(textwrap.dedent("""
        say <message> # writes a message to the public chat
        emote <message> # writes an action to the public chat
        signal # writes current location to the public chat
        """).lstrip())
    
    def help_narrative(self):
        print(textwrap.dedent("""
        note <text> # change the description of a vessel
        transform <text> # change the name and attribute of your current vessel
        """).lstrip())
    
    def help_programming(self):
        print(textwrap.dedent("""
        A Vessel program is a piece of text containing wildcards that is evaluated,
        when a vessel is used with the 'use' command. ('help with wildcards' for more info)
        An example program to check if the using vessel has a specific key could be:
        <( 'warp '~vessel.random.id if ('warpgate key' in vessel.children|map(attribute='full_name')) else 'print you need a key to use this warpgate' )>
        """).lstrip())
    
    def do_exit(self,arg):
        "exits"
        return True
    
    def do_EOF(self,args):
        "End of file, exits"
        return True
    
    def register_command(self,cmd,func):
        cmd_name="do_"+cmd
        if hasattr(self,cmd_name) and not cmd_name in self.user_cmds:
            print("Can't redefine non-user-defined function!")
            return
        self.user_cmds.add(cmd_name)
        setattr(type(self),cmd_name,func)
        setattr(self,cmd_name,types.MethodType(func,self))
    
    def document_command(self,cmd,doc):
        def func(self):
            print(doc)
        cmd_name="help_"+cmd
        setattr(type(self),cmd_name,func)
        setattr(self,cmd_name,types.MethodType(func,self))

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument("-t","--test",action="store_true",help="Run test suite")
arg_parser.add_argument("-i","--do_import",action="store_true",help="Reset Database and import Snapshot")
arg_parser.add_argument("-n","--no_interactive",action="store_true",help="Do not start interactive prompt")
arg_parser.add_argument("-v","--vessel",action="store_true",help="location is a vessel")
arg_parser.add_argument("-j","--json",action="store_true",help="json output")
arg_parser.add_argument("-e","--empty",action="store_true",help="start with an empty universe (except for ID 0)")
arg_parser.add_argument("-l","--location",type=int,help="Start location (default=random) or vessel",default=None)
arg_parser.add_argument("-db","--database",type=str,help="Database file to use",default="universe.db")
arg_parser.add_argument("commands",type=str,help="Commands to run",default=None,nargs='*')
args=arg_parser.parse_args()
#args.json=False
import json
class VesselEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Vessel):
            out={"forum":[msg for msg in obj.forum]}
            for k,v in obj.dict.items():
                print(k,v)
                if isinstance(v,Vessel):
                    out[k]=v.id
                elif (not isinstance(v,(str,bytes,dict))) and hasattr(v,"__iter__"):
                    l=[]
                    for i in v:
                        if isinstance(i,Vessel):
                            l.append(i.id)
                        else:
                            l.append(i)
                    out[k]=l
                else:
                    out[k]=v
            print(out)
            return out
        if isinstance(obj, Forum):
            return obj.dict
        return json.JSONEncoder.default(self, obj)
def serialize(data):
    return json.dumps(data,cls=VesselEncoder,sort_keys=True,indent=4)

def lua_eval(code,parser,*,reset=True,**kwargs):
    global lua,lua_globals,lua_whitelist
    if not has_lua:
        raise NotImplementedError("lupa module not loaded")
    if reset:
        for k in lua_globals:
            if k in lua_whitelist:
                continue
            del lua_globals[k]
    for v in lua_blacklist:
        lua.execute("{}=nil".format(v))
    for k,v in lua_overrides.items():
        lua.execute("{}={}".format(k,v))
    g=lua_globals
    def to_id_map(data):
        return {v.id:v for v in data}
    def timeout(message):
        raise TimeoutError(message)
    def import_filter(module,function=None):
        if not module in python_whitelist:
            raise AttributeError("Access denied: {}".format(module))
        imp_path=".".join([module,function or ""]).strip(".")
        if imp_path in python_blacklist:
            raise AttributeError("Access denied: {}".format(imp_path))
        if function and not function.startswith("_"):
            return getattr(importlib.import_module(module),function)
        elif function:
            raise AttributeError("Access denied: {}".format(function))
        return importlib.import_module(module)
    g_upd={
        #'python':import_filter("builtins"),
        'register_command':parser.register_command,
        'py_import':import_filter,
        'int':int,
        'int_s':lambda v:str(int(v)),
        'format':lambda s,*f:s.format(*f),
        'timeout':timeout,
        'template':lambda s,kwargs={}:eval_template(parser,s,parser.vessel,**kwargs),
        'cmd':lambda *cmds:parser.script(*cmds,silent=False),
        'py_print':print,
        'vessel':parser.vessel or Ghost(),
        'location':((lambda:parser.vessel.parent) if parser.vessel else (lambda:parser.location))(),
        'universe':to_id_map(Vessel.universe),
        'atlas':to_id_map(Vessel.atlas),
        'spells':to_id_map(Vessel.spells),
        'tunnels':to_id_map(Vessel.tunnels),
        'time':Clock().as_dict(),
        'nataniev':lambda tz:Clock(tz).as_dict(),
        'find_vessel':lambda id_n:Vessel.find_distant(id_n),
    }
    g_upd.update(kwargs)
    for k,v in g_upd.items():
        g[k]=v
    try:
        return False,lua.execute(code)
    except Exception as e:
        return True,e
def init_lua():
    def lua_getter(obj,attr):
        if isinstance(attr,str):
            if attr.startswith("_") and attr.endswith("_"):
                raise AttributeError("not allowed to read attribute {}".format(attr))
            if getattr(obj,"__name__",None)!=None:
                if "{}.{}".format(obj.__name__,attr) in python_blacklist:
                    if getattr(obj,attr)!=None:
                        raise AttributeError("not allowed to read attribute {}.{}".format(obj.__name__,attr))
            return getattr(obj,attr)
        return obj[attr]
    def lua_setter(obj, attr, value):
        print("SET",obj,attr,"->",value)
        if isinstance(obj,Vessel):
            if attr in obj.cols:
                return obj.__setattr__(attr,value)
        raise AttributeError("not allowed to write attribute {}".format(attr))
    lupa_config={
        "attribute_handlers":(lua_getter, lua_setter),
        "register_eval":False,
        "register_builtins":False,
        "unpack_returned_tuples":True,
    }
    lua=lupa.LuaRuntime(**lupa_config)
    debug=lua.require("debug")
    debug.sethook(lua.compile("timeout('Quota exceeded: {} instructions')".format(LUA_LIMIT)),"",LUA_LIMIT)
    lua_globals=lua.globals()
    for k in lua_globals:
        if k in lua_whitelist:
            continue
        del lua_globals[k]
    for v in lua_blacklist:
        lua.execute("{}=nil".format(v))
    for k,v in lua_overrides.items():
        lua.execute("{}={}".format(k,v))
    return lua,lua_globals
if __name__=="__main__":
    if has_lua:
        lua,lua_globals=init_lua()
    if args.test or args.do_import:
        import import_snapshot
    if args.empty:
        Forum.metadata.drop_all(engine)
        Vessel.metadata.drop_all(engine)
        
        Forum.metadata.create_all(engine)
        Vessel.metadata.create_all(engine)
        Vessel( # create root vessel
            id=0,
            attr="central",
            name="nexus",
            raw_note="The central anchor point of the universe, nothing to see here, go build something",
            locked=True,
            silent=False,
            parent_id=0,
            owner_id=0,
        )
    if args.json:
        #sys.stdout=open(os.devnull,"w")
        #sys.stderr=open(os.devnull,"w")
        #stream=open(1,"w")
        args.no_interactive=True
    if ((args.location is not None) and args.vessel):
        args.location=Vessel.get(args.location)
    parser=Cmd_Parser(args.location)
    if args.json:
        import pprint
        pprint.pprint((parser.vessel or parser.location).dict)
        #print(serialize(parser.vessel or parser.location),file=stream)
    #exit()
    if args.commands:
        parser.script(*args.commands)
    if args.test:
        parser=Cmd_Parser(20)
        parser.vessel=None
        parser.script(
            "create a unit tester",
            "become a unit tester",
            "warp to 19",
            "!exec('self.vessel.parent.locked=False')",
            "!exec('self.vessel.parent.silent=False')",
            "!exec('self.vessel.parent.locked=True')",
            "create a benchmark tool",
            "enter the benchmark tool",
            "leave",
            "enter the benchmark tool",
            "note benchmark note",
            "program create benchmark note",
            "leave",
            "use the benchmark tool",
            "create a benchmark note",
            "cast the vanish spell onto the benchmark note",
            "cast the petunia spell onto the benchmark note",
            "create a tiny quazar",
            "take the tiny quazar",
            "drop the tiny quazar",
            "inspect the tiny quazar",
            "transform into a benchmark vessel",
            "help",
            "help with wildcards",
            "help with spells",
            "help with movement",
            "help with communication",
            "help with narrative",
            "help with programming",
            "say hello",
            "emote acts like a word",
            "signal",
            "warp to 0",
            "warp to -1",
            "warp to 99999999999",
            "warp to the residences",
            "warp to the quazar",
            "warp to haven",
            "exit"
        )
    elif not args.no_interactive:
        while 1:
            try:
                parser.cmdloop()
                break
            except Exception as e:
                print("Error:",*e.args)