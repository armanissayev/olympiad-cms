"""Debugpy entry preserving fixed STDIN and participant source locations."""
import os,runpy,sys
sys.stdin=open('/box/__debug_stdin',encoding='utf-8')
sys.path.insert(0,'/box')
runpy.run_path(sys.argv[1],run_name='__main__')
