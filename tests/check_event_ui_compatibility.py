"""Execute the SDK's actual transpilers on pure C# doubles, without sts2.dll."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


def main():
    sdk = Path(sys.argv[1]).resolve()
    source = (sdk/'src/Sts2Headless/EventUiCompatibility.cs').read_text()
    sim = (sdk/'src/Sts2Headless/RunSimulator.cs').read_text()
    a = sim.index('    private Dictionary<string, object?> CrystalSphereState()')
    b = sim.index('    private Dictionary<string, object?> DoCrystalClick', a)
    grid_method = sim[a:b]
    fake = r'''
using System;
using System.Linq;
using System.Collections.Generic;
using System.Threading.Tasks;
using MegaCrit.Sts2.Core.Audio.Debug;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Vfx.Utilities;

static class Effects {
 public static int Heal, Gold, Curse, Relics, Rng;
 public static bool FightPage;
 public static string Removed="", Added="", Choices="";
 public static int DrawCase() { Rng++; return 1; }
}
namespace MegaCrit.Sts2.Core.Nodes.Vfx.Utilities {
 enum ShakeStrength { Strong, Medium }
 enum ShakeDuration { Normal }
 enum RumbleStyle { Rumble }
}
namespace MegaCrit.Sts2.Core.Entities.Players { class Player {} }
namespace MegaCrit.Sts2.Core.Context {
 static class LocalContext {
  public static bool IsMe(MegaCrit.Sts2.Core.Entities.Players.Player? p) => true;
 }
}
namespace MegaCrit.Sts2.Core.Audio.Debug {
 enum PitchVariance { None, Large }
 class NDebugAudioManager {
  public static NDebugAudioManager? Instance => null;
  public int Play(string stream, float volume=1f, PitchVariance variance=PitchVariance.None)
   => throw new Exception("Audio must be replaced");
  public void Stop(int id, float fadeTime=0.5f) => throw new Exception("Audio must be replaced");
 }
}
namespace MegaCrit.Sts2.Core.Nodes {
 class NGame {
  public static NGame? Instance => null;
  public void ScreenRumble(ShakeStrength s, ShakeDuration d, RumbleStyle r)
   => throw new Exception("Rumble must be replaced");
  public void ScreenShakeTrauma(ShakeStrength s) => throw new Exception("Shake must be replaced");
 }
}
namespace MegaCrit.Sts2.Core.Models.Events {
 class DenseVegetation {
  private async Task Rest() {
   Effects.Heal++;
   int id=NDebugAudioManager.Instance!.Play("sleep");
   await Task.Delay(1);
   NDebugAudioManager.Instance!.Stop(id);
   NDebugAudioManager.Instance!.Play("hiss",1f,PitchVariance.Large);
   NGame.Instance!.ScreenRumble(ShakeStrength.Medium,ShakeDuration.Normal,RumbleStyle.Rumble);
   Effects.FightPage=true;
  }
 }
 class JungleMazeAdventure {
  private async Task SafetyInNumbers() {
   NDebugAudioManager.Instance!.Play("hey"); await Task.Delay(1); Effects.Gold+=51;
  }
 }
 class Amalgamator {
  private async Task CombineStrikes() {
   Effects.Removed+="S";NDebugAudioManager.Instance?.Play("smith");
   NGame.Instance!.ScreenShakeTrauma(ShakeStrength.Strong);
   await Task.Delay(1); NDebugAudioManager.Instance?.Play("smith");
   NGame.Instance!.ScreenShakeTrauma(ShakeStrength.Strong); Effects.Added+="S";
  }
  private async Task CombineDefends() {
   Effects.Removed+="D";NDebugAudioManager.Instance?.Play("smith");
   NGame.Instance!.ScreenShakeTrauma(ShakeStrength.Strong);
   await Task.Delay(1);NDebugAudioManager.Instance?.Play("smith");
   NGame.Instance!.ScreenShakeTrauma(ShakeStrength.Strong); Effects.Added+="D";
  }
 }
 class PunchOff {
  private async Task Nab() {
   Effects.Curse++;NGame.Instance!.ScreenShakeTrauma(ShakeStrength.Strong);
   NDebugAudioManager.Instance?.Play("blunt");await Task.Delay(1);Effects.Relics++;
  }
 }
 class Trial {
  private readonly MegaCrit.Sts2.Core.Entities.Players.Player Owner=new();
  private Task Accept() {
   if(MegaCrit.Sts2.Core.Context.LocalContext.IsMe(Owner))throw new Exception("Absent first portrait");
   int n=Effects.DrawCase();AddVfxAnchoredToPortrait("scene");
   if(MegaCrit.Sts2.Core.Context.LocalContext.IsMe(Owner))throw new Exception("Absent second portrait");
   Effects.Choices=n+":Guilty/Innocent";return Task.CompletedTask;
  }
  private void AddVfxAnchoredToPortrait(string p)=>throw new Exception("Absent portrait");
 }
}
namespace Sts2Headless {
 class FakeRelic {}
 class FakeCurse {}
 class Cell {
  public bool IsHidden; public object? Stored;
  public object? Item => IsHidden ? throw new Exception("Read an obscured item") : Stored;
 }
 class GridSize { public int X=2,Y=2; }
 class CrystalSphereMinigame {
  public Cell[,] cells=new Cell[2,2];public GridSize GridSize=new();public int DivinationCount=3;
 }
 class RunState { public List<object> Players=new(){new object()}; }
 class Adapter {
  CrystalSphereMinigame? _crystalSphere;
  RunState _runState=new();
  object RunContext()=>new{act=2};object PlayerSummary(object p)=>new{hp=64};
  public Adapter(object hidden) {
   _crystalSphere=new();
   for(int x=0;x<2;x++)for(int y=0;y<2;y++)
    _crystalSphere.cells[x,y]=new Cell{IsHidden=true,Stored=hidden};
   _crystalSphere.cells[0,0]=new Cell{IsHidden=false,Stored=new FakeRelic()};
  }
  public string Read()=>System.Text.Json.JsonSerializer.Serialize(CrystalSphereState());
__GRID_METHOD__
 }
 class Probe {
  static void Require(bool ok,string why) {if(!ok)throw new Exception(why);}
  static Task Callback(object e,string n)=>(Task)e.GetType().GetMethod(n,
   System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Instance)!.Invoke(e,null)!;
  static async Task Main() {
   bool failed=false;
   try {await Callback(new MegaCrit.Sts2.Core.Models.Events.DenseVegetation(),"Rest");}
   catch(NullReferenceException){failed=true;}
   Require(failed&&!Effects.FightPage,"Original absent-node fault was not reproduced");Effects.Heal=0;
   EventUiCompatibility.Install();
   await Callback(new MegaCrit.Sts2.Core.Models.Events.DenseVegetation(),"Rest");
   Require(Effects.Heal==1&&Effects.FightPage,"Rest lost its mandatory next fight");
   await Callback(new MegaCrit.Sts2.Core.Models.Events.JungleMazeAdventure(),"SafetyInNumbers");
   Require(Effects.Gold==51,"Join Forces lost gold");
   await Callback(new MegaCrit.Sts2.Core.Models.Events.Amalgamator(),"CombineStrikes");
   await Callback(new MegaCrit.Sts2.Core.Models.Events.Amalgamator(),"CombineDefends");
   Require(Effects.Removed=="SD"&&Effects.Added=="SD","Fusion card effects changed");
   await Callback(new MegaCrit.Sts2.Core.Models.Events.PunchOff(),"Nab");
   Require(Effects.Curse==1&&Effects.Relics==1,"Nab lost curse or relic");
   await Callback(new MegaCrit.Sts2.Core.Models.Events.Trial(),"Accept");
   Require(Effects.Rng==1&&Effects.Choices=="1:Guilty/Innocent","Trial RNG or choices changed");
   var a=new Adapter(new FakeRelic()).Read();var b=new Adapter(new FakeCurse()).Read();
   Require(a==b,"Obscured item identities leaked");
   Require(a.Contains("FakeRelic")&&!a.Contains("FakeCurse"),"Visible item presentation changed");
   Require(!AppDomain.CurrentDomain.GetAssemblies().Any(x=>x.GetName().Name=="sts2"),"Game assembly loaded");
   Console.WriteLine("8 pure C# event UI/visible-grid checks passed; no game assembly loaded");
  }
 }
}
'''.replace('__GRID_METHOD__', grid_method)
    with tempfile.TemporaryDirectory(prefix='sts2-event-ui-pure-') as directory:
        path=Path(directory)
        (path/'Compatibility.cs').write_text(source)
        (path/'Probe.cs').write_text(fake)
        references=''.join(f'<Reference Include="{name}"><HintPath>{sdk}/lib/{name}.dll</HintPath></Reference>'
                           for name in ['0Harmony','MonoMod.Backports','MonoMod.ILHelpers'])
        (path/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<OutputType>Exe</OutputType><TargetFramework>net9.0</TargetFramework>'
            '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
            '</PropertyGroup><ItemGroup>'+references+'</ItemGroup></Project>')
        env=dict(os.environ,DOTNET_PROCESSOR_COUNT='2',DOTNET_CLI_TELEMETRY_OPTOUT='1',
                 TMPDIR=str(path),MONOMOD_HelperDropPath=str(path))
        subprocess.run(['/opt/dotnet9/dotnet','run','--project',str(path/'Probe.csproj')],
                       env=env,check=True)


if __name__ == '__main__':
    main()
