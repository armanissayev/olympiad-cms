"""Fixed debugger exec wrapper; installed read-only, never accepts shell text."""
import os,sys
os.dup2(os.open('/box/__debug_stdin',os.O_RDONLY),0)
os.execv(sys.argv[1],sys.argv[1:])
