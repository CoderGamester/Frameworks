// Tier 2 packer for the unity-package-release skill.
//
// Copied by release.py into a CACHED throwaway project at
// ~/Library/Caches/GameLovers/UpmPacker/Assets/Editor/UpmPack.cs -- deliberately
// outside any git repo, so a Unity run can never generate .meta files inside the
// Frameworks repo (which has no Assets/ Editor folder and a rule that .meta files
// are only ever committed after the editor creates them), and so it never
// contends for the real project's lock.
//
// Invoked as:
//   Unity -batchmode -nographics -silent-crashes -disable-assembly-updater \
//         -projectPath <cache> -logFile <log> -executeMethod UpmPack.Run \
//         -packageFolder <pkg> -outDir <out> -resultFile <res> -timeoutSeconds 300
//
// Note there is no -quit: we exit explicitly via EditorApplication.Exit so the
// exit code is ours rather than Unity's, and so a failure is a distinct code.

using System;
using System.IO;
using System.Threading;
using UnityEditor;
using UnityEditor.PackageManager;
using UnityEditor.PackageManager.Requests;

public static class UpmPack
{
    public static void Run()
    {
        string resultFile = null;

        try
        {
            var packageFolder = Path.GetFullPath(RequireArg("-packageFolder"));
            var outDir = Path.GetFullPath(RequireArg("-outDir"));
            resultFile = RequireArg("-resultFile");

            var timeoutSeconds = 300;
            var rawTimeout = GetArg("-timeoutSeconds");
            if (!string.IsNullOrEmpty(rawTimeout))
            {
                int.TryParse(rawTimeout, out timeoutSeconds);
            }

            if (!File.Exists(Path.Combine(packageFolder, "package.json")))
            {
                throw new FileNotFoundException($"no package.json under '{packageFolder}'");
            }

            Directory.CreateDirectory(outDir);

            // 2-arg overload ONLY. The org-id overload attests against the signed-in
            // Unity org, and this machine's license belongs to a work organisation --
            // stamping that into a public OSS artifact is exactly the leak found in the
            // published statechart 0.9.4. Attested packing goes through the `upm pack`
            // CLI (tier 1) with an explicit --organization-id instead.
            var request = Client.Pack(packageFolder, outDir);

            // Request.Status refreshes the native UPM operation on every read, and the
            // real work happens in the upm child process over IPC -- so polling
            // advances the state machine under -batchmode with no EditorApplication
            // .update pump.
            var deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
            while (!request.IsCompleted)
            {
                if (DateTime.UtcNow > deadline)
                {
                    throw new TimeoutException(
                        $"Client.Pack still {request.Status} after {timeoutSeconds}s");
                }

                Thread.Sleep(100);
            }

            if (request.Status != StatusCode.Success)
            {
                var error = request.Error;
                throw new Exception(
                    $"Client.Pack failed: {error?.errorCode} :: {error?.message}");
            }

            var tarball = request.Result != null ? request.Result.tarballPath : null;
            if (string.IsNullOrEmpty(tarball) || !File.Exists(tarball))
            {
                throw new FileNotFoundException(
                    $"Pack reported Success but no file exists at '{tarball}'");
            }

            // A result file rather than stdout: batchmode stdout interleaves the whole
            // editor log, and ordering between Console.Out and the log writer is not
            // something to bet a release on.
            File.WriteAllText(resultFile, "OK\n" + tarball + "\n");
            EditorApplication.Exit(0);
        }
        catch (Exception e)
        {
            try
            {
                if (resultFile != null)
                {
                    File.WriteAllText(resultFile, "FAIL\n" + e.GetType().Name + ": " + e.Message + "\n");
                }
            }
            catch
            {
                // Nothing useful to do -- the non-zero exit code still signals failure.
            }

            Console.Error.WriteLine("UPMPACK_FAIL " + e);
            EditorApplication.Exit(20);
        }
    }

    private static string GetArg(string name)
    {
        var args = Environment.GetCommandLineArgs();
        for (var i = 0; i < args.Length - 1; i++)
        {
            if (args[i] == name)
            {
                return args[i + 1];
            }
        }

        return null;
    }

    private static string RequireArg(string name)
    {
        var value = GetArg(name);
        if (string.IsNullOrEmpty(value))
        {
            throw new ArgumentException($"missing required argument {name}");
        }

        return value;
    }
}
