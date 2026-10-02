package fr.cyberdodo.dodotopia

import android.Manifest
import android.content.ClipData
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat

/**
 * Écran de l'appli de test : état du service d'accessibilité, test de capture écran + son,
 * derniers résultats et partage du journal. Le métronome, lui, se pilote depuis la bulle, par-dessus le jeu.
 */
class MainActivity : AppCompatActivity() {

    // Même refusées, on continue : sans micro on mesure quand même l'écran, sans notification le service tourne quand même.
    private val permissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        consentement.launch(getSystemService(MediaProjectionManager::class.java).createScreenCaptureIntent())
    }

    private val consentement = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { retour ->
        val donnees = retour.data
        if (retour.resultCode == RESULT_OK && donnees != null) {
            ContextCompat.startForegroundService(this, CaptureService.intention(this, donnees))
        } else {
            Resultats.capture.value = "Capture refusée : rien n'a été mesuré."
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        SpikeLog.init(this)
        setContentView(R.layout.activity_main)

        // targetSdk 35 dessine sous les barres système : on rend la place en marge.
        val racine = findViewById<View>(R.id.racine)
        ViewCompat.setOnApplyWindowInsetsListener(racine) { vue, insets ->
            val bords = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            vue.setPadding(bords.left, bords.top, bords.right, bords.bottom)
            insets
        }

        findViewById<View>(R.id.btnAcces).setOnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        findViewById<View>(R.id.btnInfos).setOnClickListener {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)))
        }
        findViewById<View>(R.id.btnCapture).setOnClickListener { lancerCapture() }
        findViewById<View>(R.id.btnPartager).setOnClickListener { partagerJournal() }
        findViewById<View>(R.id.btnEffacer).setOnClickListener {
            SpikeLog.effacer()
            Toast.makeText(this, R.string.journal_efface, Toast.LENGTH_SHORT).show()
        }

        val acces = findViewById<TextView>(R.id.txtAcces)
        DodoAccessibilityService.actif.observe(this) { actif ->
            acces.setText(if (actif) R.string.acces_actif else R.string.acces_inactif)
            acces.setBackgroundResource(if (actif) R.drawable.pastille_ok else R.drawable.pastille_alerte)
            acces.setTextColor(getColor(if (actif) R.color.c_ok else R.color.c_danger_text))
        }
        val capture = findViewById<TextView>(R.id.txtCapture)
        Resultats.capture.observe(this) { capture.text = it }
        val metronome = findViewById<TextView>(R.id.txtMetronome)
        Resultats.metronome.observe(this) { metronome.text = it }
    }

    private fun lancerCapture() {
        val demandes = mutableListOf(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) demandes += Manifest.permission.POST_NOTIFICATIONS
        permissions.launch(demandes.toTypedArray())
    }

    private fun partagerJournal() {
        val fichier = SpikeLog.fichier(this)
        if (!fichier.exists() || fichier.length() == 0L) {
            Toast.makeText(this, R.string.journal_absent, Toast.LENGTH_SHORT).show()
            return
        }
        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", fichier)
        val envoi = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_STREAM, uri)
            putExtra(Intent.EXTRA_SUBJECT, "DodoTopia mobile : journal de l'étape 1")
            // ClipData : sans lui, certaines applis cibles ne reçoivent pas le droit de lecture.
            clipData = ClipData.newRawUri("spike.log", uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivity(Intent.createChooser(envoi, getString(R.string.journal_partager)))
    }
}
