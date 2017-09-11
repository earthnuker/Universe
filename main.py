import os
import io
import sys
import cmd
import textwrap
import readline
import argparse

from functools import wraps
from datetime import datetime

import jinja2
import jinja2.meta
import jinja2.sandbox

from date_time import Clock
from vessel import Vessel,Ghost,Forum,split_vessel_name,clean_vessel_name

if not os.path.isfile("universe.db"):
    import import_snapshot

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
    def modifies_known_mutable(self,obj,attr):
        #print(obj,attr)
        return super().modifies_known_mutable(obj,attr)

def lformat(iterable, pattern="{}"):
    if iterable is None or isinstance(iterable, jinja2.Undefined):
        return iterable
    #print <( atlas|lformat("{full_name_with_id} by {owner}")|list )>
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

def eval_template(cmd,vessel,target=None,recursive=False):
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
        template=jinja.parse(cmd)
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

class Cmd_Parser(cmd.Cmd):
    prompt="> "
    def __init__(self,location=None,*,test_mode=False):
        self.in_program = False
        self.vessel=None
        self.forum_size=5
        self.visible_count=5
        if location is None:
            while True:
                self.location=Vessel.random()
                if self.location.locked:
                    continue
                if self.location.silent:
                    continue
                break
        else:
            self.location=Vessel.get(location)
        self.test_mode=test_mode
        ret=super(type(self),self).__init__()
        print("Universe v0.1")
        print()
        self.script("look",silent=True)
        return ret
    
    @property
    def netcat(self):
        return os.environ.get("NCAT_REMOTE_ADDR",None) or os.environ.get("NCAT_REMOTE_PORT",None)
    
    @property
    def prompt(self):
        prompt=""
        if self.vessel:
            prompt="{}@{}".format(self.vessel.id,self.vessel.parent_id)
        elif self.location:
            prompt="None@{}".format(self.location.id)
        if self.in_program:
            prompt="(program){}".format(prompt)
        return "{}> ".format(prompt)
    
    def cmdloop(self):
        self.cmdqueue.append("")
        return super(type(self),self).cmdloop(self.intro)
    
    def precmd(self,line):
        if not line:
            return line
        Vessel.update()
        cmd=line.split()[0]
        if cmd in ["program","note"]:
            return line
        try:
            return eval_template(line,self.vessel)
        except Exception as e:
            if self.test_mode:
                raise
            #print <( atlas|map(attribute='dict')|lformat("{full_name_with_id} by {owner}")|list )>
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
            article="your" if self.vessel.parent.owner_id==self.vessel.id else "the"
            paradox="Paradox" if self.vessel.parent.paradox else " "
            head="You are the {} in {} {} {}".format(self.vessel.full_name_with_id,article,self.vessel.parent.full_name_with_id,paradox).strip()
            print()
            print(head)
            if self.vessel.parent.note.strip():
                print()
                print(eval_template(self.vessel.parent.note,self.vessel).strip())
            forum=self.vessel.parent.forum[-self.forum_size:]
            if forum and not line.strip().startswith("forum"):
                print()
                for message in forum:
                    msg=message['rendered']
                    if msg:
                        print(msg)
            visible=self.vessel.parent.visible
            if visible:
                print()
                print("You can see:")
                for vessel in visible[:self.visible_count]:
                    if vessel.parent_id==self.vessel.id:
                        continue
                    print(" -",vessel.full_name_with_id)
                if len(visible)>self.visible_count:
                    print("And {} more vessels (use *look* to see all)".format(len(visible)-self.visible_count))
        else:
            print("You are a ghost in the {}".format(self.location.full_name_with_id))
            if self.location.note.strip():
                print()
                print(eval_template(self.location.note,self.vessel or Ghost()).strip())
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
        if not cmd:
            return ''
        assert not self.test_mode
        super(type(self),self).default(cmd)
    
    def script(self,*args,silent=False):
        for line in args:
            if not silent:
                print("{}{}".format(self.prompt,line))
            line=self.precmd(line)
            stop=self.onecmd(line)
            stop=self.postcmd(stop,line)
    
    def do_look(self,name):
        "Lists all visible Vessels."
        if name:
            print("Look takes no arguments")
            return
        if self.vessel:
            article="your" if self.vessel.parent.owner_id==self.vessel.id else "the"
            paradox="Paradox" if self.vessel.parent.paradox else " "
            head="You are the {} in {} {} {}".format(self.vessel.full_name_with_id,article,self.vessel.parent.full_name_with_id,paradox).strip()
            print()
            print(head)
            if self.vessel.parent.note.strip():
                print()
                print(eval_template(self.vessel.parent.note,self.vessel).strip())
            visible=self.vessel.parent.visible
            print()
            if not visible:
                print("You can see nothing")
                return
            print("You can see:")
            for vessel in visible:
                print(" -",vessel.full_name_with_id)
        else:
            print("You are a ghost in the {}".format(self.location.full_name_with_id))
            if self.location.note.strip():
                print()
                print(eval_template(self.location.note,self.vessel or Ghost()).strip())
            forum=self.location.forum[-self.forum_size:]
            if forum:
                print()
                print("Last 5 messages")
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
        #print(self.location.find_visible(None))
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
        print("The {} is owned by the {}, has a rating of {}".format(vessel.full_name,vessel.owner.full_name_with_id,vessel.rating),end="")
        if vessel.stem.id!=vessel.id:
            print(" and is currently {} levels deep within the {} paradox".format(vessel.depth,vessel.stem.full_name))
        else:
            print(" and is a paradox".format(vessel.full_name))
        if vessel.stem.id!=vessel.id:
            print("Stem:",vessel.stem)
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
        for n,sibling in enumerate(vessel.children):
            if not n:
                print("Children:")
            print(" -",sibling.full_name_with_id)
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
        V=Vessel(name)
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
    
    @needs_vessel
    def do_program(self,program):
        "Add an automation program to a vessel, making it available to the use command. ('help with programming' for more info)"
        if self.vessel.parent.owner_id==self.vessel.id:
            self.vessel.parent.program=program
        else:
            print("You do not own",self.vessel.parent.full_name)
    
    @needs_vessel
    def do_note(self,note):
        "Add a description to the current parent vessel."
        if self.vessel.parent.owner_id==self.vessel.id:
            self.vessel.parent.raw_note=note
        else:
            print("You do not own",self.vessel.parent.full_name)
    
    @needs_vessel
    def do_transform(self,name):
        "Change your current vessel name and attribute."
        attr,name=split_vessel_name(name)
        self.vessel.attr=attr
        self.vessel.name=name
    
    
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
        print("Warping to {}".format(vessel.full_name_with_id))
        self.vessel.parent_id=vessel.id
    
    def do_print(self,name):
        "Prints it's arguments, useful for messages or testing programs"
        if name:
            print(name)
    
    if not netcat.fget(netcat):
        def do_shell(self,cmd):
            "Evaluate python code"
            try:
                print(eval(cmd))
            except Exception as e:
                print("Error:",e)
    
    def do_locate(self,name):
        "Locates a vessel by name"
        res=Vessel.find_distant(name)
        if res:
            print("Found",res.full_name_with_id)
            return
        print("{} not found".format(name))
    
    @needs_vessel
    def do_set(self,name):
        "Directly write attributes for a owned vessel, the set command is meant to be used with programs and casted as spells."
        attr,value=name.split()
        if attr in ["is_{}".format(flag) for flag in ("locked","hidden","silent","tunnel")]:
            attr=attr[3:]
            if value.lower()=="true":
                value=True
            elif value.lower()=="false":
                value=False
            else:
                print("Invalid value: {}".format(value))
                return
            if self.vessel.parent.owner_id==self.vessel.id:
                setattr(self.parent,attr,value)
            else:
                print("You do not own the {}".format(self.vessel.parent.full_name_with_id))
            return
        print("Invalid attribute: {}".format(attr))
    
    
    @needs_vessel
    def do_take(self,name):
        "Move a visible vessel into your current vessel."
        target=self.vessel.find_visible(name)
        if target:
            if target.locked:
                print("The",name,"is locked")
                return
            if target.owner_id==self.vessel.id:
                target.parent_id=self.vessel.id
                print("You took the",target.full_name)
            else:
                print("You do not own the",target.full_name)
        else:
            print("There is no",name,"here")
    
    @needs_vessel
    def do_drop(self,name):
        "Move a visible vessel out of your current vessel into your parent vessel."
        target=self.vessel.find_child(name)
        if target:
            if self.vessel.parent.locked:
                print("The",self.vessel.parent.full_name,"is locked")
                return
            target.parent_id=self.vessel.parent_id
            print("You dropped the",target.full_name)
        else:
            print("You have no",name)

    @needs_vessel
    def do_use(self,name):
        "Execute a vessels program"
        target=self.vessel.find_visible(name)
        if target and target.program:
            command = eval_template(target.program,self.vessel)
            if command.startswith("!") or command.split()[0]=="shell":
                print("Programs cannot evaluate python code")
                return
            self.in_program=True
            self.script(command)
            self.in_program=False
        else:
            print("There is no",name,"here")
    
    @needs_vessel
    def do_transform(self,name):
        "Change your current vessel's name and attribute"
        attr,name=split_vessel_name(name)
        self.vessel.attr=attr
        self.vessel.name=name
    
    @needs_vessel
    def do_cast(self,name):
        "Remotely execute a program, optionally in the context of another vessel (using 'cast ... onto ...')"
        if " on " in name:
            spell,target_name=map(clean_vessel_name,name.split(" on "))
            target=self.vessel.find_visible(target_name)
        elif " onto " in name:
            spell,target_name=map(clean_vessel_name,name.split(" onto "))
            target=self.vessel.find_visible(target_name)
        else:
            spell=clean_vessel_name(name)
            target_name=self.vessel.full_name
            target=self.vessel
        try:
            spell_program=next(filter(lambda vessel:vessel.full_name==spell,Vessel.spells)).program
            spell_command=eval_template(spell_program,self.vessel,target)
        except StopIteration:
            print("The {} does not exist".format(spell))
            return
        if not target:
            print("Target {} does not exist".format(target_name))
            return
        print("casting the {} ({} -> {}) onto the {}".format(spell,spell_program,spell_command,target.full_name_with_id))
        if spell_command.startswith("!"):
            print("Spells cannot evaluate python code")
            return
        if self.vessel:
            vessel_id=self.vessel.id
        else:
            vessel_id=None
        self.vessel=target
        self.in_program=True
        self.script(spell_command)
        self.in_program=False
        self.vessel=Vessel.get(vessel_id)
    
    def do_say(self,message):
        "Add a message into the global dialog."
        message=message.strip()
        if message:
            msg=Forum(host_id=self.vessel.parent.id,from_id=self.vessel.id,message=message)
            print(msg.str)
        return
    
    def do_signal(self,name):
        "Broadcast your current visible parent vessel."
        name=name.strip().title()
        if name.isnumeric():
            if not Vessel.get(int(name)):
                print("Target vessel does not exist")
                return
            msg=Forum(host_id=self.vessel.parent.id,from_id=self.vessel.id,message=name)
        elif name:
            vessel=Vessel.find_distant(name)
            if vessel:
                msg=Forum(host_id=self.vessel.parent.id,from_id=self.vessel.id,message=str(vessel.id))
            else:
                print("Invalid argument")
                return
        else:
            msg=Forum(host_id=self.vessel.parent.id,from_id=self.vessel.id,message=str(self.vessel.parent.id))
        print(msg.str)
    
    def do_emote(self,message):
        "Add an emote message into the global dialog."
        if message:
            message="me "+message.strip()
            msg=Forum(host_id=self.vessel.parent.id,from_id=self.vessel.id,message=message)
        return
    
    def do_help(self,name):
        "Prints help."
        if name.startswith("with "):
            name=name.replace("with ","")
        
        super().do_help(name)
    
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
        'taget': target of a spell program (only defined when casting a spell)
        
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
        A program needs to be programmed, locked, and have the '<something> spell' format to qualify.
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

arg_parser = argparse.ArgumentParser()
group = arg_parser.add_mutually_exclusive_group()
group.add_argument("-t","--test",action="store_true",help="Run test suite")
arg_parser.add_argument("location",type=int,help="Start location (default=random)",default=None,nargs='?')
args=arg_parser.parse_args()

if __name__=="__main__":
    if args.test:
        Cmd_Parser(20,test_mode=True).script(
            "create a test vessel",
            "become a test vessel",
            "warp to 19",
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
    Cmd_Parser(args.location).cmdloop()
    