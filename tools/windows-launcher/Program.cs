using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

namespace ClearMarkLauncher
{
    internal static class Program
    {
        private const string ProjectRoot = @"E:\wartermark_remove";

        private static void Log(string message)
        {
            string runtimeDirectory = Path.Combine(ProjectRoot, ".run");
            Directory.CreateDirectory(runtimeDirectory);
            File.AppendAllText(
                Path.Combine(runtimeDirectory, "launcher.log"),
                DateTime.Now.ToString("s") + " " + message + Environment.NewLine);
        }

        [STAThread]
        private static void Main()
        {
            string managerPath = Path.Combine(ProjectRoot, "clearmark-manager.ps1");
            string executableName = Path.GetFileNameWithoutExtension(Assembly.GetExecutingAssembly().Location);
            string action = executableName.StartsWith("Stop", StringComparison.OrdinalIgnoreCase)
                ? "stop"
                : "start";

            try
            {
                Log("launch " + action + " from " + Assembly.GetExecutingAssembly().Location);
                if (!File.Exists(managerPath))
                {
                    MessageBox.Show("ClearMark controller was not found.", "ClearMark", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }

                string windowsDirectory = Environment.GetEnvironmentVariable("WINDIR") ?? @"C:\Windows";
                string powershellPath = Path.Combine(
                    windowsDirectory, "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
                ProcessStartInfo startInfo = new ProcessStartInfo();
                startInfo.FileName = powershellPath;
                startInfo.Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + managerPath + "\" " + action;
                startInfo.WorkingDirectory = ProjectRoot;
                startInfo.UseShellExecute = true;
                startInfo.WindowStyle = ProcessWindowStyle.Hidden;
                if (Process.Start(startInfo) == null) { throw new InvalidOperationException("Launcher did not start."); }
                Log("powershell dispatched");
            }
            catch (Exception error)
            {
                Log("error: " + error.ToString());
                MessageBox.Show(error.Message, "ClearMark", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }
}
