using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class Launcher {
    [STAThread]
    static void Main() {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string settings = Path.Combine(root, "basketball_master", "python-path.txt");
        string python = File.Exists(settings) ? File.ReadAllText(settings).Trim() : "pythonw.exe";
        try {
            var start = new ProcessStartInfo(python, "-m basketball_master");
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            Process.Start(start);
        } catch (Exception error) {
            MessageBox.Show("Unable to start Basketball Edit Master. Run setup.bat first.\n" + error.Message);
        }
    }
}
