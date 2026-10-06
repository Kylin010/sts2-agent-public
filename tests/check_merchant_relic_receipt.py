"""Run installed merchant methods against pure purchase/prompt/fault doubles."""
from pathlib import Path
import os,subprocess,sys,tempfile

def main():
 source=(Path(sys.argv[1])/'src/Sts2Headless/RunSimulator.cs').read_text()
 a=source.index('    private Dictionary<string, object?> DoBuyRelic(')
 b=source.index('    private Dictionary<string, object?> DoBuyPotion(',a)
 method=source[a:b];before='--expect-before' in sys.argv[2:]
 helper=''
 if not before:
  a=source.index('    private void SettleMerchantPurchase(')
  b=source.index('    private int _lastEventOptionCount;',a)
  helper=source[a:b]
  execute=source[source.index('    public Dictionary<string, object?> ExecuteAction('):]
  execute=execute[:execute.index('            switch (action)')]
  assert '_merchantPurchaseFailure != null' in execute
  assert '_merchantPurchaseTask != null' in execute
  assert 'action != "select_cards"' in execute
  assert 'try { SettleMerchantPurchase(); }' in source
  assert '_merchantPurchaseFailure = null;' in source
 fake=r'''
using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using System.Threading;
class Lantern{}
class MembershipCard{}
class ReplacementRelic{}
class Player {public int Gold=300;public List<object> Relics=new();}
class Inventory {public List<Entry> RelicEntries=new();}
class MerchantRoom {public Inventory inv=new();public Inventory GetLocalInventory()=>inv;}
class RunState {public object CurrentRoom;public RunState(object room){CurrentRoom=room;}}
class FakePump {public Action? OnPump;public void Pump(){OnPump?.Invoke();}}
class Selector {public volatile bool HasPending;public bool HasPendingReward;}
class Entry {
 public Player player;public object? Model=new Lantern();public bool Courier,Discount,Fail,Select,Decline;
 public int BaseCost=100,Calls;public int Cost=>Discount?BaseCost/2:BaseCost;public bool IsStocked=>Model!=null;
 public TaskCompletionSource<bool> Pending=new();public Selector selector;
 public Entry(Player p,Selector s){player=p;selector=s;}
 public async Task<bool> OnTryPurchaseWrapper(Inventory inv){
  Calls++;
  if(Fail)throw new InvalidOperationException("Real native purchase failure");
  if(Decline)return false;
  if(Select){selector.HasPending=true;await Pending.Task;}
  player.Gold-=Cost;player.Relics.Add(Model!);
  if(Model is MembershipCard)Discount=true;
  Model=Courier?new ReplacementRelic():null;
  if(Courier)BaseCost=180;
  return true;
 }
}
class Probe {
 RunState? _runState;FakePump _syncCtx=new();Selector _cardSelector=new();object? _pendingBundles;
 TaskCompletionSource<IEnumerable<object>>? _pendingBundleTcs;
 Task<bool>? _merchantPurchaseTask;Exception? _merchantPurchaseFailure;
 string _merchantReceiptName="";int _merchantReceiptPrice;
 static List<string> Logs=new();
 static void Log(string message)=>Logs.Add(message);
 Dictionary<string,object?> Error(string msg)=>new(){{"type","error"},{"message",msg}};
 Dictionary<string,object?> DetectDecisionPoint(){
  if(_merchantPurchaseFailure!=null)return Error("MERCHANT_FAULT: "+_merchantPurchaseFailure.Message);
  __SETTLE__
  return new(){{"type","decision"},{"decision",_cardSelector.HasPending?"card_select":"shop"}};
 }
__HELPER__
__METHOD__
 static void Require(bool v,string why){if(!v)throw new Exception(why);}
 static (Probe,Player,Entry) Make(){
  var p=new Probe();var player=new Player();var room=new MerchantRoom();p._runState=new(room);
  var e=new Entry(player,p._cardSelector);room.inv.RelicEntries.Add(e);Logs.Clear();return(p,player,e);
 }
 static Dictionary<string,object?> Buy(Probe p,Player player)=>p.DoBuyRelic(player,new(){{"relic_index",0}});
 static void Main(){
  var(p,pl,e)=Make();var r=Buy(p,pl);
  Require(e.Calls==1&&pl.Gold==200&&pl.Relics.Count==1&&!e.IsStocked,"Native payment/obtain/clear lost");
__BEFORE__
  Require((string)r["decision"]! == "shop"&&Logs.Contains("Bought relic: Lantern for 100g"),"Successful cleared slot logged as failure");
  (p,pl,e)=Make();e.Courier=true;r=Buy(p,pl);
  Require(pl.Gold==200&&e.IsStocked&&e.Model is ReplacementRelic&&Logs.Contains("Bought relic: Lantern for 100g"),"Restocked slot overwrote original receipt");
  (p,pl,e)=Make();e.Model=new MembershipCard();r=Buy(p,pl);
  Require(pl.Gold==200&&e.Cost==50&&Logs.Contains("Bought relic: MembershipCard for 100g"),"Post-pickup discount changed recorded price");
  (p,pl,e)=Make();e.Fail=true;r=Buy(p,pl);
  Require((string)r["type"]! == "error"&&((string)r["message"]!).Contains("Real native purchase failure")&&pl.Relics.Count==0,"Real failure accepted as success");
  (p,pl,e)=Make();e.Select=true;r=Buy(p,pl);
  Require((string)r["decision"]! == "card_select"&&e.Pending.Task.IsCompleted==false&&p._merchantPurchaseTask!=null,"Genuine pickup selection lost");
  p._cardSelector.HasPending=false;e.Pending.SetResult(true);r=p.DetectDecisionPoint();
  Require((string)r["decision"]! == "shop"&&p._merchantPurchaseTask==null&&pl.Gold==200&&!e.IsStocked,"Pickup resumed before actual native completion");
  (p,pl,e)=Make();e.Decline=true;r=Buy(p,pl);
  Require((string)r["type"]! == "error"&&p._merchantPurchaseFailure!=null&&pl.Gold==300,"Declined native purchase accepted");
  (p,pl,e)=Make();e.Select=true;r=Buy(p,pl);p._cardSelector.HasPending=false;
  e.Pending.SetException(new InvalidOperationException("Failure after pickup choice"));r=p.DetectDecisionPoint();
  Require((string)r["type"]! == "error"&&((string)r["message"]!).Contains("Failure after pickup choice")&&p._merchantPurchaseTask!=null,"Late pickup fault lost");
  r=p.DetectDecisionPoint();Require((string)r["type"]! == "error"&&e.Calls==1,"Fault not latched");
  (p,pl,e)=Make();p._merchantPurchaseTask=new TaskCompletionSource<bool>().Task;
  try{p.SettleMerchantPurchase(20);throw new Exception("Timeout accepted");}catch(TimeoutException){}
  Require(p._merchantPurchaseFailure is TimeoutException&&p._merchantPurchaseTask!=null,"Timed out task discarded");
  (p,pl,e)=Make();p._merchantPurchaseTask=new TaskCompletionSource<bool>().Task;
  p._syncCtx.OnPump=()=>throw new InvalidOperationException("Pump failure");
  try{p.SettleMerchantPurchase();throw new Exception("Pump failure accepted");}catch(InvalidOperationException){}
  Require(p._merchantPurchaseFailure?.Message=="Pump failure","Pump exception not latched");
  Require(!Array.Exists(AppDomain.CurrentDomain.GetAssemblies(),a=>a.GetName().Name=="sts2"),"Game assembly loaded");
  Console.WriteLine("9 pure merchant receipt/prompt/late-fault/timeout/pump checks passed; no game assembly loaded");
 }
}
'''.replace('__METHOD__',method).replace('__HELPER__',helper).replace('__SETTLE__','' if before else 'try{SettleMerchantPurchase();}catch(Exception ex){return Error("MERCHANT_FAULT: "+ex.Message);}')
 if before:
  a=fake.index('__BEFORE__');b=fake.index('  Require(!Array.Exists',a)
  fake=fake[:a]+'Require((string)r["type"]! == "error", "Original failure not reproduced");\n'+fake[b:]
  fake=fake.replace('9 pure merchant receipt/prompt/late-fault/timeout/pump checks passed; no game assembly loaded','Original native purchase succeeded but SDK returned false error; no game assembly loaded')
 else:fake=fake.replace('__BEFORE__','')
 with tempfile.TemporaryDirectory(prefix='sts2-merchant-receipt-')as folder:
  p=Path(folder);(p/'Probe.cs').write_text(fake)
  (p/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net9.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
  subprocess.run(['/opt/dotnet9/dotnet','run','--project',str(p/'Probe.csproj'),'--verbosity','quiet'],check=True,env=dict(os.environ,DOTNET_PROCESSOR_COUNT='2'))
if __name__=='__main__':main()
