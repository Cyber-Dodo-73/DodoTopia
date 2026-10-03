package fr.cyberdodo.dodotopia

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.ImageView
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.os.LocaleListCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat

/**
 * Réglages de l'appli : langue, apparence (clair, sombre, comme le téléphone), durée d'appui, retour à
 * la présentation, diagnostic (mesures et journal à partager) et à propos. Ouvert par la roue dentée de l'accueil.
 */
class ReglagesActivity : AppCompatActivity() {

    // Même refusées, on continue : sans micro on mesure quand même l'écran, sans notification le service tourne quand même.
    private val permissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        consentement.launch(getSystemService(MediaProjectionManager::class.java).createScreenCaptureIntent())
    }

    private val consentement = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { retour ->
        val donnees = retour.data
        if (retour.resultCode == RESULT_OK && donnees != null) {
            ContextCompat.startForegroundService(this, CaptureService.intention(this, donnees))
        } else {
            Resultats.capture.value = getString(R.string.capture_refusee)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        Apparence.appliquer(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_reglages)

        // targetSdk 35 dessine sous les barres système : on rend la place en marge.
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.racine)) { vue, insets ->
            val bords = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            vue.setPadding(bords.left, bords.top, bords.right, bords.bottom)
            insets
        }
        findViewById<View>(R.id.logoReglages).clipToOutline = true
        findViewById<View>(R.id.btnRetour).setOnClickListener { finish() }
        findViewById<TextView>(R.id.txtVersion).text = getString(R.string.sous_titre, BuildConfig.VERSION_NAME)

        // ---- Langue : vide = celle du téléphone. Android recrée l'écran dans la langue choisie.
        val langue = AppCompatDelegate.getApplicationLocales().toLanguageTags().substringBefore('-')
        val langues = listOf(R.id.langueSysteme to "", R.id.langueFr to "fr", R.id.langueEn to "en")
        for ((id, code) in langues) {
            findViewById<View>(id).apply {
                isSelected = code == langue
                setOnClickListener {
                    if (code == langue) return@setOnClickListener
                    tic()
                    AppCompatDelegate.setApplicationLocales(
                        if (code.isEmpty()) LocaleListCompat.getEmptyLocaleList() else LocaleListCompat.forLanguageTags(code)
                    )
                }
            }
        }

        // ---- Apparence
        val themes = listOf(
            R.id.themeSysteme to Apparence.SYSTEME, R.id.themeClair to Apparence.CLAIR, R.id.themeSombre to Apparence.SOMBRE,
        )
        // Si le choix change vraiment les couleurs, AppCompat recrée l'écran ; sinon seules les puces bougent.
        fun majThemes() {
            val apparence = Apparence.choix(this)
            for ((id, choix) in themes) findViewById<View>(id).isSelected = choix == apparence
        }
        for ((id, choix) in themes) {
            findViewById<View>(id).setOnClickListener { puce ->
                if (choix == Apparence.choix(this)) return@setOnClickListener
                puce.tic()
                Apparence.definir(this, choix)
                majThemes()
            }
        }
        majThemes()

        // ---- Lecture : notes tenues et arrangeur (lus par le lecteur et la bibliothèque à chaque morceau)
        fun interrupteur(id: Int, lire: () -> Boolean, ecrire: (Boolean) -> Unit) {
            findViewById<View>(id).apply {
                isSelected = lire()
                commeInterrupteur()
                setOnClickListener {
                    it.tic()
                    ecrire(!it.isSelected)
                    it.isSelected = lire()
                }
            }
        }
        interrupteur(R.id.swTenues, { Lecteur.notesTenues(this) }) { Lecteur.definirNotesTenues(this, it) }
        interrupteur(R.id.swArrangeur, { Bibliotheque.arrangeur(this) }) { Bibliotheque.definirArrangeur(this, it) }

        // ---- Durée d'appui : le même réglage que dans la bulle (onglet Outils), mêmes bornes.
        val prefs = Preferences.prefs(this)
        val valeur = findViewById<TextView>(R.id.reglAppuiValeur)
        val moins = findViewById<View>(R.id.reglAppuiMoins)
        val plus = findViewById<View>(R.id.reglAppuiPlus)
        fun majAppui() {
            val ms = prefs.getInt(APPUI, APPUI_DEFAUT)
            valeur.text = getString(R.string.duree_ms, ms)
            moins.isEnabled = ms > APPUI_MINI
            plus.isEnabled = ms < APPUI_MAXI
            moins.alpha = if (moins.isEnabled) 1f else 0.4f
            plus.alpha = if (plus.isEnabled) 1f else 0.4f
        }
        fun changer(saut: Int) {
            val ms = (prefs.getInt(APPUI, APPUI_DEFAUT) + saut).coerceIn(APPUI_MINI, APPUI_MAXI)
            prefs.edit().putInt(APPUI, ms).apply()
            majAppui()
        }
        moins.setOnClickListener { it.tic(); changer(-APPUI_SAUT) }
        plus.setOnClickListener { it.tic(); changer(APPUI_SAUT) }
        majAppui()

        // ---- Aide
        findViewById<View>(R.id.ligneBienvenue).setOnClickListener {
            setResult(RESULT_OK, Intent().putExtra(REVOIR_BIENVENUE, true))
            finish()
        }

        // ---- Diagnostic, replié par défaut
        val bloc = findViewById<View>(R.id.blocDiagnostic)
        val chevron = findViewById<ImageView>(R.id.chevronDiagnostic)
        fun deplier(ouvert: Boolean) {
            bloc.visibility = if (ouvert) View.VISIBLE else View.GONE
            chevron.setImageResource(if (ouvert) R.drawable.ic_moins else R.drawable.ic_plus)
        }
        deplier(savedInstanceState?.getBoolean(DIAGNOSTIC_OUVERT) == true)
        findViewById<View>(R.id.titreDiagnostic).setOnClickListener { deplier(bloc.visibility != View.VISIBLE) }
        findViewById<View>(R.id.btnCapture).setOnClickListener { lancerCapture() }
        findViewById<View>(R.id.btnPartager).setOnClickListener { partagerJournal() }
        findViewById<View>(R.id.btnEffacer).setOnClickListener {
            SpikeLog.effacer()
            Annonce.montrer(this, R.string.journal_efface)
        }
        val capture = findViewById<TextView>(R.id.txtCapture)
        Resultats.capture.observe(this) { capture.text = it }
        val metronome = findViewById<TextView>(R.id.txtMetronome)
        Resultats.metronome.observe(this) { metronome.text = it }

        // ---- À propos
        lien(R.id.lienSite, R.string.url_site)
        lien(R.id.lienConfidentialite, R.string.url_confidentialite)
        lien(R.id.lienConditions, R.string.url_conditions)
        lien(R.id.lienMentions, R.string.url_mentions)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putBoolean(DIAGNOSTIC_OUVERT, findViewById<View>(R.id.blocDiagnostic).visibility == View.VISIBLE)
    }

    private fun lien(id: Int, adresse: Int) {
        findViewById<View>(id).setOnClickListener {
            try {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(getString(adresse))))
            } catch (e: ActivityNotFoundException) {
                Annonce.montrer(this, R.string.navigateur_absent, erreur = true)
            }
        }
    }

    private fun lancerCapture() {
        val demandes = mutableListOf(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) demandes += Manifest.permission.POST_NOTIFICATIONS
        permissions.launch(demandes.toTypedArray())
    }

    private fun partagerJournal() {
        val fichier = SpikeLog.fichier(this)
        if (!fichier.exists() || fichier.length() == 0L) {
            Annonce.montrer(this, R.string.journal_absent)
            return
        }
        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", fichier)
        val envoi = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_STREAM, uri)
            putExtra(Intent.EXTRA_SUBJECT, "DodoTopia Mobile ${BuildConfig.VERSION_NAME} : journal")
            // ClipData : sans lui, certaines applis cibles ne reçoivent pas le droit de lecture.
            clipData = ClipData.newRawUri("spike.log", uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivity(Intent.createChooser(envoi, getString(R.string.journal_partager)))
    }

    companion object {
        /** Extra du résultat : l'accueil doit rouvrir l'écran de bienvenue. */
        const val REVOIR_BIENVENUE = "revoir_bienvenue"
        private const val DIAGNOSTIC_OUVERT = "diagnostic_ouvert"

        // Clé, valeur par défaut et bornes de la bulle (Overlay.kt, onglet Outils) : à garder identiques.
        private const val APPUI = "appui_ms"
        private const val APPUI_DEFAUT = 40
        private const val APPUI_MINI = 20
        private const val APPUI_MAXI = 200
        private const val APPUI_SAUT = 10
    }
}
