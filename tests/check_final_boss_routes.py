"""Execute the installed SDK's final-boss method against pure C# doubles.

Usage: python3 tests/check_final_boss_routes.py /path/to/sts2-cli
No game assembly, game process, save/load, or native state setting is used.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


def main():
    sdk = Path(sys.argv[1])
    source = (sdk / 'src/Sts2Headless/RunSimulator.cs').read_text()
    start = source.index('    private Dictionary<string, object?> FinishFinalActBoss()')
    end = source.index('    private Dictionary<string, object?> GameOverState(', start)
    method = source[start:end]
    # Check both SDK entry points use this method, not an unconditional win.
    for name, following in [('DoProceed', '#endregion'),
                            ('DetectPostCombatState', 'private Dictionary<string, object?> CardRewardState(')]:
        begin = source.index('private Dictionary<string, object?> ' + name + '(')
        body = source[begin:source.index(following, begin + len(name))]
        assert 'return FinishFinalActBoss();' in body, name

    harness = r'''
using System;
using System.Collections.Generic;

enum AscensionLevel { DoubleBoss }
class RunManager {
    public static RunManager Instance = new();
    public bool Double;
    public bool HasAscension(AscensionLevel _) => Double;
}
struct MapCoord {
    public int col, row;
    public MapCoord(int c, int r) { col = c; row = r; }
}
class MapPoint {
    public MapCoord coord;
    public MapPoint(int c, int r) { coord = new(c, r); }
}
class FakeMap {
    public MapPoint BossMapPoint = new(3, 16);
    public MapPoint? SecondBossMapPoint = new(3, 17);
}
class MapRoom {}
class FakeState {
    public FakeMap? Map = new();
    public MapCoord? CurrentMapCoord = new MapCoord(3, 16);
    public object? CurrentRoom = new object();
    public int Hp = 23;
}
class Probe {
    FakeState? _runState = new();
    int maps, victories;
    bool failMap;
    void Log(string _) {}
    void ForceToMap() { maps++; if (!failMap) _runState!.CurrentRoom = new MapRoom(); }
    Dictionary<string, object?> MapSelectState() => new() { ["decision"] = "map_select" };
    Dictionary<string, object?> GameOverState(bool won) {
        if (won) victories++;
        return new() { ["decision"] = "game_over", ["victory"] = won };
    }
    static Dictionary<string, object?> Error(string _) => new() { ["type"] = "error" };
    void HealBetweenActs() => throw new Exception("No between-boss heal is allowed");
__METHOD__
    static void Check(int test, Action<Probe> setup, string expected, int mapCalls, int wins) {
        RunManager.Instance.Double = true;
        var p = new Probe(); setup(p);
        var result = p.FinishFinalActBoss();
        var actual = (string?)result.GetValueOrDefault("decision") ?? (string?)result.GetValueOrDefault("type");
        if (actual != expected || p.maps != mapCalls || p.victories != wins || p._runState!.Hp != 23)
            throw new Exception($"Route case {test} failed: {actual}");
    }
    static void Main() {
        Check(1, p => {}, "map_select", 1, 0);
        Check(2, p => p._runState!.CurrentMapCoord = new MapCoord(3,17), "game_over", 0, 1);
        Check(3, p => { RunManager.Instance.Double = false; p._runState!.Map!.SecondBossMapPoint = null; }, "game_over", 0, 1);
        Check(4, p => p._runState!.CurrentMapCoord = null, "error", 0, 0);
        Check(5, p => p._runState!.CurrentMapCoord = new MapCoord(2,7), "error", 0, 0);
        Check(6, p => p._runState!.Map!.SecondBossMapPoint = null, "error", 0, 0);
        Check(7, p => p.failMap = true, "error", 1, 0);
        Check(8, p => p._runState!.Map = null, "error", 0, 0);
        Console.WriteLine("8 pure C# final-boss routes passed; no game assembly loaded");
    }
}
'''.replace('__METHOD__', method)
    with tempfile.TemporaryDirectory(prefix='sts2-final-boss-pure-') as folder:
        root = Path(folder)
        (root / 'Probe.cs').write_text(harness)
        (root / 'Probe.csproj').write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<OutputType>Exe</OutputType><TargetFramework>net9.0</TargetFramework>'
            '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
            '</PropertyGroup></Project>')
        dotnet = os.environ.get('DOTNET', '/opt/dotnet9/dotnet')
        subprocess.run([dotnet, 'run', '--project', str(root / 'Probe.csproj'),
                        '--verbosity', 'quiet'], check=True,
                       env=dict(os.environ, DOTNET_ROOT=str(Path(dotnet).parent),
                                DOTNET_PROCESSOR_COUNT='4'))


if __name__ == '__main__':
    main()
