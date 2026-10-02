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
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat

/**
 * Deux écrans, repris des ébauches « DodoTopia Mobile » :
 * « Avant de commencer » (les autorisations) puis l'accueil de l'appli de test, où l'on allume
 * la bulle. Rien ne s'affiche par-dessus le jeu tant que le service n'est pas activé ET que
 * l'interrupteur « Bulle dans le jeu » n'est pas allumé.
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

    private lateinit var ecranAutorisations: View
    private lateinit var ecranAccueil: View
    private lateinit var retour: OnBackPressedCallback

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        SpikeLog.init(this)
        setContentView(R.layout.activity_main)

        // targetSdk 35 dessine sous les barres système : on rend la place en marge.
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.racine)) { vue, insets ->
            val bords = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            vue.setPadding(bords.left, bords.top, bords.right, bords.bottom)
            insets
        }

        ecranAutorisations = findViewById(R.id.ecranAutorisations)
        ecranAccueil = findViewById(R.id.ecranAccueil)
        // Depuis l'accueil, la roue ramène aux autorisations ; « retour » en revient.
        retour = object : OnBackPressedCallback(false) {
            override fun handleOnBackPressed() = montrer(accueil = true)
        }
        onBackPressedDispatcher.addCallback(this, retour)

        // ---- Avant de commencer
        findViewById<View>(R.id.btnAcces).setOnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        findViewById<View>(R.id.lienRestreint).setOnClickListener {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)))
        }
        findViewById<View>(R.id.btnContinuer).setOnClickListener {
            Preferences.definirConfigFaite(this)
            montrer(accueil = true)
        }

        // ---- Accueil
        findViewById<View>(R.id.btnReglages).setOnClickListener { montrer(accueil = false) }
        findViewById<View>(R.id.swBulle).setOnClickListener { interrupteur ->
            Preferences.definirBulle(this, !interrupteur.isSelected)
            DodoAccessibilityService.instance?.appliquerBulle()
            majBulle()
        }
        findViewById<View>(R.id.btnCapture).setOnClickListener { lancerCapture() }
        findViewById<View>(R.id.btnPartager).setOnClickListener { partagerJournal() }
        findViewById<View>(R.id.btnEffacer).setOnClickListener {
            SpikeLog.effacer()
            Toast.makeText(this, R.string.journal_efface, Toast.LENGTH_SHORT).show()
        }

        DodoAccessibilityService.actif.observe(this) { majService(it) }
        val capture = findViewById<TextView>(R.id.txtCapture)
        Resultats.capture.observe(this) { capture.text = it }
        val metronome = findViewById<TextView>(R.id.txtMetronome)
        Resultats.metronome.observe(this) { metronome.text = it }

        montrer(accueil = Preferences.configFaite(this))
    }

    private fun montrer(accueil: Boolean) {
        ecranAccueil.visibility = if (accueil) View.VISIBLE else View.GONE
        ecranAutorisations.visibility = if (accueil) View.GONE else View.VISIBLE
        retour.isEnabled = !accueil && Preferences.configFaite(this)
    }

    /** Reflète l'état du service sur l'écran des autorisations, comme dans l'ébauche (« À activer » puis « Activé »). */
    private fun majService(actif: Boolean) {
        fun pilule(id: Int, texte: Int, ok: Boolean) = findViewById<TextView>(id).apply {
            setText(texte)
            setBackgroundResource(if (ok) R.drawable.pilule_ok else R.drawable.pilule_attente)
            setTextColor(getColor(if (ok) R.color.c_ok else R.color.c_ambre_texte))
        }
        pilule(R.id.pilService, if (actif) R.string.pil_active else R.string.pil_a_activer, actif)
        pilule(R.id.pilBulle, if (actif) R.string.pil_accordee else R.string.pil_avec_service, actif)
        findViewById<View>(R.id.carteService).setBackgroundResource(if (actif) R.drawable.carte else R.drawable.carte_attente)
        findViewById<View>(R.id.btnAcces).visibility = if (actif) View.GONE else View.VISIBLE
        findViewById<View>(R.id.lienRestreint).visibility = if (actif) View.GONE else View.VISIBLE

        findViewById<TextView>(R.id.btnContinuer).apply {
            setText(if (actif) R.string.continuer_pret else R.string.continuer_sans)
            setBackgroundResource(if (actif) R.drawable.btn_teal else R.drawable.btn_creme)
            setTextColor(getColor(if (actif) R.color.blanc else R.color.c_text_2))
        }
        findViewById<TextView>(R.id.txtContinuer)
            .setText(if (actif) R.string.continuer_pret_aide else R.string.continuer_sans_aide)
        majBulle()
    }

    /** L'interrupteur n'a de sens que service activé ; sinon il reste éteint et grisé. */
    private fun majBulle() {
        val service = DodoAccessibilityService.actif.value == true
        val active = service && Preferences.bulleActive(this)
        findViewById<View>(R.id.swBulle).apply {
            isEnabled = service
            isSelected = active
        }
        findViewById<TextView>(R.id.txtBulle).setText(
            when {
                !service -> R.string.bulle_sans_service
                active -> R.string.bulle_active
                else -> R.string.bulle_inactive
            }
        )
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
