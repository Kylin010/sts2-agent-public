"""Exercise the installed SDK's context adapter with pure C# async work."""
from pathlib import Path
import os,subprocess,sys,tempfile

def main():
    source=(Path(sys.argv[1])/'src/Sts2Headless/RunSimulator.cs').read_text()
    a=source.index('        public static void EventCombatContextPrefix(')
    b=source.index('        public static bool CrystalScreenPrefix(',a)
    methods=source[a:b]
    code=r'''
using System;
using System.Collections.Concurrent;
using System.Threading;
using System.Threading.Tasks;
class QueueContext:SynchronizationContext {
 public ConcurrentQueue<(SendOrPostCallback,object?)> Work=new();
 public override void Post(SendOrPostCallback cb,object? s)=>Work.Enqueue((cb,s));
 public void Pump(){while(Work.TryDequeue(out var w))w.Item1(w.Item2);}
}
class Probe {
 static QueueContext _syncCtx=new();static Probe? _bundleSimRef=new();
__METHODS__
 static void Require(bool b,string m){if(!b)throw new Exception(m);}
 static void Main(){
  var prior=new SynchronizationContext();SynchronizationContext.SetSynchronizationContext(prior);
  EventCombatContextPrefix(out var saved);
  Require(saved==prior&&SynchronizationContext.Current==_syncCtx,"Context not captured before native start");
  SynchronizationContext? resumed=null;int thread=-1;int here=Environment.CurrentManagedThreadId;
  async Task NativeWork(){await Task.Delay(10);resumed=SynchronizationContext.Current;thread=Environment.CurrentManagedThreadId;}
  var task=NativeWork();
  Require(EventCombatContextFinalizer(saved,null)==null&&SynchronizationContext.Current==prior,"Success context not restored");
  var deadline=Environment.TickCount64+2000;
  while(!task.IsCompleted&&Environment.TickCount64<deadline){
   SynchronizationContext.SetSynchronizationContext(_syncCtx);_syncCtx.Pump();
   SynchronizationContext.SetSynchronizationContext(prior);Thread.Sleep(1);
  }
  Require(task.IsCompleted&&resumed==_syncCtx&&thread==here,"Native continuation escaped serialized SDK context");
  var fault=new InvalidOperationException("Original native failure");EventCombatContextPrefix(out saved);
  Require(EventCombatContextFinalizer(saved,fault)==fault&&SynchronizationContext.Current==prior,"Failure replaced or leaked context");
  Require(!Array.Exists(AppDomain.CurrentDomain.GetAssemblies(),a=>a.GetName().Name=="sts2"),"Game loaded");
  Console.WriteLine("4 pure context capture/restoration checks passed; no game assembly loaded");
 }
}
'''.replace('__METHODS__',methods)
    with tempfile.TemporaryDirectory(prefix='sts2-event-context-')as folder:
        path=Path(folder);(path/'Probe.cs').write_text(code)
        (path/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net9.0</TargetFramework><Nullable>enable</Nullable></PropertyGroup></Project>')
        subprocess.run(['/opt/dotnet9/dotnet','run','--project',str(path/'Probe.csproj'),'--verbosity','quiet'],check=True,env=dict(os.environ,DOTNET_PROCESSOR_COUNT='2'))
if __name__=='__main__':main()
