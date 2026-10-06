"""Run the installed SDK's event fence/selector with pure C# doubles.

No game assembly, native game, save/load, or native state mutation is used.
--selector-only also runs on the unpatched SDK to reproduce publication races.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


def main():
    source = (Path(sys.argv[1]) / 'src/Sts2Headless/RunSimulator.cs').read_text()
    selector_only = '--selector-only' in sys.argv[2:]
    begin = source.index('    internal class HeadlessCardSelector :')
    end = source.index('    internal static class YieldPatches', begin)
    selector = source[begin:end]
    methods = ''
    if not selector_only:
        begin = source.index('    private bool HasEventInput(')
        end = source.index('    private Dictionary<string, object?> DetectDecisionPoint()', begin)
        methods = source[begin:end]
        assert 'pumpContext: false' in source[end:end + 850]
        assert 'ResolvePendingDeferredByIndices' in source
        execute = source[source.index('public Dictionary<string, object?> ExecuteAction('):]
        assert execute.index('if (_eventFailure != null)') < execute.index('switch (action)')
        assert 'EVENT_FAULT' in execute[:1400]
    prefix = r'''
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using System.Reflection;

class CardModel { public string Name; public CardModel(string n) { Name=n; } }
class CardRewardAlternative {}
namespace MegaCrit.Sts2.Core.TestSupport {
    interface ICardSelector {}
    struct CardRewardSelection { public global::CardModel? card; public object? alternative; }
}
namespace MegaCrit.Sts2.Core.Entities.Cards {
    class CardCreationResult {
        public global::CardModel Card;
        public CardCreationResult(global::CardModel card) { Card=card; }
    }
}
class CombatManager {
    public static CombatManager Instance=new();
    public bool IsInProgress;
}
class FakePump { public int Count; public bool Reject;
    public void Pump() { Count++; if(Reject) throw new Exception("Unexpected context pump"); }
}
class InlineContext : SynchronizationContext {
    public override void Post(SendOrPostCallback d, object? s) => d(s);
}
class CallbackWriter : StringWriter {
    public Action? Callback;
    public override void WriteLine(string? s) { var f=Callback; Callback=null; f?.Invoke(); }
}
class Probe {
    HeadlessCardSelector _cardSelector=new();
    FakePump _syncCtx=new();
    class CrystalSphereMinigame { public bool IsFinished; }
    CrystalSphereMinigame? _crystalSphere;
    Exception? _eventFailure;
    object? _pendingBundles;
    TaskCompletionSource<IEnumerable<CardModel>>? _pendingBundleTcs;
__SELECTOR__
__METHODS__
    static void Require(bool v, string why) { if(!v) throw new Exception(why); }
    static void Publication() {
        var s=new HeadlessCardSelector(); var card=new CardModel("Visible A");
        var writer=new CallbackWriter { Callback=()=>s.ResolvePending(new[]{card}) };
        Console.SetError(writer);
        var task=s.GetSelectedCards(new[]{card,new CardModel("Visible B")},1,1);
        Console.SetError(TextWriter.Null);
        Require(task.IsCompleted && task.Result.Single()==card, "Published promise lost after immediate reply");
        Require(!s.HasPending, "Completed prompt still visible");
    }
__CASES__
    static void Main() { Console.SetError(TextWriter.Null); Publication(); __RUN__ }
}
'''
    cases = r'''
    static void DelayedCompletion() {
        var p=new Probe(); bool settled=false;
        Task? task=Task.Run(async()=>{ await Task.Delay(30); settled=true; });
        p.WaitForEventTask(ref task,"fake event",maxWaitMs:1000);
        Require(settled && task==null,"Returned old event before callback finished");
    }
    static void VisibleInput() {
        var p=new Probe(); var card=new CardModel("A");
        var selection=p._cardSelector.GetSelectedCards(new[]{card,new CardModel("B")},1,1);
        Task? task=Task.Delay(100);
        p.WaitForEventTask(ref task,"next prompt",maxWaitMs:50);
        Require(task!=null && p._cardSelector.HasPending,"Real next selection swallowed");
        p._cardSelector.ResolvePending(new[]{card}); selection.GetAwaiter().GetResult();
    }
    static void CompletedBundle() {
        var p=new Probe(); p._pendingBundles=new object();
        p._pendingBundleTcs=new(); p._pendingBundleTcs.SetResult(Array.Empty<CardModel>());
        Task? task=Task.Delay(25);
        p.WaitForEventTask(ref task,"answered bundle",maxWaitMs:1000);
        Require(task==null,"Answered bundle incorrectly exposes stale input");
    }
    static void ActualFault() {
        var p=new Probe(); Task? task=Task.FromException(new InvalidOperationException("Original fault"));
        var original=task;
        try { p.WaitForEventTask(ref task,"fault"); throw new Exception("Fault swallowed"); }
        catch(InvalidOperationException ex) {
            Require(ex.Message=="Original fault","Replaced original fault");
            Require(task==original && p._eventFailure==ex,"Faulted callback/latch lost");
        }
    }
    static void PendingTimeout() {
        var p=new Probe(); var promise=new TaskCompletionSource(); Task? task=promise.Task;
        try { p.WaitForEventTask(ref task,"pending",maxWaitMs:20); throw new Exception("Timeout missing"); }
        catch(TimeoutException ex) {
            Require(task==promise.Task,"Incomplete callback discarded");
            Require(p._eventFailure==ex,"Timeout was not latched");
        }
        promise.SetResult();
    }
    static void CrystalInput() {
        var p=new Probe { _crystalSphere=new CrystalSphereMinigame() };
        var promise=new TaskCompletionSource(); Task? task=promise.Task;
        p.WaitForEventTask(ref task,"grid prompt",maxWaitMs:20);
        Require(task==promise.Task && p._eventFailure==null,"Genuine crystal prompt swallowed");
        promise.SetResult();
    }
    static void CrystalClickWait() {
        var p=new Probe { _crystalSphere=new CrystalSphereMinigame() };
        bool clicked=false;
        Task? task=Task.Run(async()=>{await Task.Delay(30); clicked=true;});
        p.WaitForEventTask(ref task,"grid click",pumpContext:false,maxWaitMs:1000,allowCrystalInput:false);
        Require(clicked && task==null,"Old grid mask returned before click completed");
    }
    static void ActiveCombat() {
        var p=new Probe(); var promise=new TaskCompletionSource(); Task? task=promise.Task;
        CombatManager.Instance.IsInProgress=true;
        try { p.WaitForEventTask(ref task,"combat",maxWaitMs:20); Require(task!=null,"Combat callback consumed"); }
        finally { CombatManager.Instance.IsInProgress=false; promise.SetResult(); }
    }
    static void AnsweredReward() {
        var s=new HeadlessCardSelector(); var waiter=new ManualResetEventSlim(true);
        typeof(HeadlessCardSelector).GetField("_rewardWait",BindingFlags.Instance|BindingFlags.NonPublic)!.SetValue(s,waiter);
        typeof(HeadlessCardSelector).GetProperty("PendingRewardCards")!.SetValue(s,
            new List<MegaCrit.Sts2.Core.Entities.Cards.CardCreationResult>{new(new CardModel("A"))});
        Require(!s.HasPendingReward,"Answered reward still selectable while callback finishes");
    }
    static void DeferredSkip() {
        var s=new HeadlessCardSelector();
        var selection=s.GetSelectedCards(new[]{new CardModel("A"),new CardModel("B")},0,2);
        var reply=s.ResolvePendingDeferredByIndices(Array.Empty<int>());
        reply.GetAwaiter().GetResult();
        Require(!s.HasPending && !selection.Result.Any(),"Deferred legal skip lost");
    }
    static void NestedBlockingReward() {
        var p=new Probe(); var card=new CardModel("A"); bool finished=false;
        Task? eventTask=Task.Run(async()=>{
            SynchronizationContext.SetSynchronizationContext(new InlineContext());
            await p._cardSelector.GetSelectedCards(new[]{card,new CardModel("B")},1,1);
            var reward=p._cardSelector.GetSelectedCardReward(
                new[]{new MegaCrit.Sts2.Core.Entities.Cards.CardCreationResult(card)},Array.Empty<CardRewardAlternative>());
            Require(reward.card==card,"Wrong visible nested reward selected"); finished=true;
        });
        p.WaitForEventTask(ref eventTask,"first event prompt",maxWaitMs:2000);
        Require(p._cardSelector.HasPending,"First prompt missing");
        Task? reply=p._cardSelector.ResolvePendingDeferredByIndices(new[]{0});
        p._syncCtx.Reject=true;
        p.WaitForEventTask(ref reply,"event reply",pumpContext:false,maxWaitMs:2000);
        Require(reply!=null && p._cardSelector.HasPendingReward,"Blocking next reward prevented response");
        Require(!p._cardSelector.HasPending,"Old prompt cleared after completing reply");
        p._cardSelector.ResolveReward(0);
        p.WaitForEventTask(ref reply,"reply done",pumpContext:false,maxWaitMs:2000);
        p._syncCtx.Reject=false;
        p.WaitForEventTask(ref eventTask,"event done",maxWaitMs:2000);
        Require(finished && reply==null && eventTask==null,"Nested event did not finish");
    }
'''
    run = ('Console.WriteLine("Selector publication passed; no game assembly loaded");' if selector_only else
           'DelayedCompletion(); VisibleInput(); CompletedBundle(); ActualFault(); PendingTimeout(); '
           'ActiveCombat(); AnsweredReward(); DeferredSkip(); NestedBlockingReward(); CrystalInput(); CrystalClickWait(); '
           'Console.WriteLine("12 pure C# event/selector checks passed; no game assembly loaded");')
    harness = prefix.replace('__SELECTOR__', selector).replace('__METHODS__', methods)
    harness = harness.replace('__CASES__', '' if selector_only else cases).replace('__RUN__', run)
    with tempfile.TemporaryDirectory(prefix='sts2-event-task-pure-') as folder:
        root=Path(folder)
        (root/'Probe.cs').write_text(harness)
        (root/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<OutputType>Exe</OutputType><TargetFramework>net9.0</TargetFramework>'
            '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
            '</PropertyGroup></Project>')
        dotnet=os.environ.get('DOTNET','/opt/dotnet9/dotnet')
        subprocess.run([dotnet,'run','--project',str(root/'Probe.csproj'),'--verbosity','quiet'],
            check=True,env=dict(os.environ,DOTNET_ROOT=str(Path(dotnet).parent),DOTNET_PROCESSOR_COUNT='4'))


if __name__ == '__main__':
    main()
