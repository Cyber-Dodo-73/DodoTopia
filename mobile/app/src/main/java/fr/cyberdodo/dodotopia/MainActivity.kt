package fr.cyberdodo.dodotopia

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import java.io.IOException
import java.util.concurrent.Executors

/**
 * Deux écrans : la bienvenue (les trois étapes, dont l'activation du service) puis l'accueil,
 * où l'on prépare ce que la bulle jouera dans le jeu : morceaux importés et clavier de l'instrument.
 * Rien ne s'affiche par-dessus le jeu tant que le service n'est pas activé ET que l'interrupteur
 * « Bulle dans le jeu » n'est pas allumé. Les réglages et le diagnostic sont dans [ReglagesActivity].
 */
class MainActivity : AppCompatActivity() {

    private val choixFichiers = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        for (uri in uris) importer(uri)
    }

    private val reglages = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { retour ->
        if (retour.data?.getBooleanExtra(ReglagesActivity.REVOIR_BIENVENUE, false) == true) montrer(accueil = false)
        // L'arrangeur a pu changer : les parts de notes exactes sont à recalculer (onResume refait les listes).
        couvertures.clear()
    }

    private lateinit var biblio: Bibliotheque
    private lateinit var ecranBienvenue: View
    private lateinit var ecranAccueil: View
    private lateinit var retour: OnBackPressedCallback

    /** Part de notes exactes par morceau et par clavier : calculée hors du fil principal, gardée tant que l'activité vit. */
    private val couvertures = HashMap<String, Int>()
    private val calcul = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        // Clair, sombre ou comme le téléphone : à poser avant que l'activité ne choisisse ses ressources.
        Apparence.appliquer(this)
        super.onCreate(savedInstanceState)
        SpikeLog.init(this)
        biblio = Bibliotheque(this)
        setContentView(R.layout.activity_main)

        // targetSdk 35 dessine sous les barres système : on rend la place en marge.
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.racine)) { vue, insets ->
            val bords = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            vue.setPadding(bords.left, bords.top, bords.right, bords.bottom)
            insets
        }

        // L'attribut clipToOutline des mises en page n'est lu qu'à partir d'Android 12.
        findViewById<View>(R.id.logoBienvenue).clipToOutline = true
        findViewById<View>(R.id.logoAccueil).clipToOutline = true

        ecranBienvenue = findViewById(R.id.ecranBienvenue)
        ecranAccueil = findViewById(R.id.ecranAccueil)
        if (resources.getBoolean(R.bool.ecran_large)) disposerEnLarge()
        // Depuis l'accueil, le bouclier ramène à la bienvenue ; « retour » en revient.
        retour = object : OnBackPressedCallback(false) {
            override fun handleOnBackPressed() = montrer(accueil = true)
        }
        onBackPressedDispatcher.addCallback(this, retour)

        // ---- Bienvenue
        val reglagesAccessibilite = View.OnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        findViewById<View>(R.id.btnAcces).setOnClickListener(reglagesAccessibilite)
        findViewById<View>(R.id.lienRestreint).setOnClickListener {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)))
        }
        findViewById<View>(R.id.btnContinuer).setOnClickListener {
            Preferences.definirConfigFaite(this)
            montrer(accueil = true)
        }

        // ---- Accueil
        findViewById<TextView>(R.id.txtVersion).text = getString(R.string.sous_titre, BuildConfig.VERSION_NAME)
        findViewById<View>(R.id.btnAide).setOnClickListener { montrer(accueil = false) }
        findViewById<View>(R.id.btnReglages).setOnClickListener {
            reglages.launch(Intent(this, ReglagesActivity::class.java))
        }
        findViewById<View>(R.id.ligneService).setOnClickListener {
            if (DodoAccessibilityService.actif.value != true) montrer(accueil = false)
        }
        findViewById<View>(R.id.swBulle).apply {
            setOnClickListener { interrupteur ->
                interrupteur.tic()
                Preferences.definirBulle(this@MainActivity, !interrupteur.isSelected)
                DodoAccessibilityService.instance?.appliquerBulle()
                majBulle()
            }
            commeInterrupteur()
        }
        findViewById<View>(R.id.btnJeu).setOnClickListener { ouvrirJeu() }
        findViewById<View>(R.id.btnImporter).setOnClickListener {
            // Beaucoup de gestionnaires de fichiers ne connaissent pas le type MIDI : on laisse tout choisir, la lecture tranche.
            choixFichiers.launch(arrayOf("audio/midi", "audio/x-midi", "audio/mid", "audio/sp-midi", "application/x-midi", "application/octet-stream", "*/*"))
        }

        // ---- Compte, bibliothèque en ligne, salon
        if (BuildConfig.DEBUG) reglagesDeTest()
        BandeauCompte(this)
        val pageBiblio = PageBiblio(this, biblio) { majListes() }
        PageSalon(this, biblio)
        PageDessin(this)
        val pages = listOf(R.id.navJouer to R.id.pageJouer, R.id.navDessin to R.id.pageDessin, R.id.navBiblio to R.id.pageBiblio, R.id.navSalon to R.id.pageSalon)
        fun ouvrirPage(nav: Int) {
            page = nav
            for ((bouton, page) in pages) {
                findViewById<View>(bouton).isSelected = bouton == nav
                val vue = findViewById<View>(page)
                val montre = bouton == nav
                if (montre && vue.visibility != View.VISIBLE) apparaitre(vue)
                vue.visibility = if (montre) View.VISIBLE else View.GONE
            }
            if (nav == R.id.navBiblio) pageBiblio.ouvrir()
        }
        for ((bouton, _) in pages) findViewById<View>(bouton).setOnClickListener { ouvrirPage(bouton) }
        // Après une rotation ou un changement de thème, on revient sur la page qu'on regardait.
        val ouverte = savedInstanceState?.getInt(PAGE, 0) ?: 0
        ouvrirPage(if (pages.any { it.first == ouverte }) ouverte else R.id.navJouer)

        // Mise à jour : la vérification part au lancement (PageBiblio). Une version plus récente est proposée
        // une fois, où qu'on soit ; le téléchargement et l'installation se suivent sur la carte de la Bibliothèque.
        var proposee = savedInstanceState != null
        MiseAJour.etat.observe(this) { e ->
            val v = e.version
            if (v == null || proposee || e.fichier != null || e.progression != null) return@observe
            proposee = true
            MaterialAlertDialogBuilder(this)
                .setTitle(getString(R.string.maj_titre, v.version))
                .setMessage(v.notes.take(600).ifBlank { getString(R.string.maj_taille, "%.1f".format(v.taille / 1_048_576.0)) })
                .setNegativeButton(R.string.continuer_sans, null)
                .setPositiveButton(R.string.maj_telecharger) { _, _ ->
                    ouvrirPage(R.id.navBiblio)
                    if (MiseAJour.peutInstaller(this)) MiseAJour.telecharger(this, v) else Connexion.ouvrir(this, v.adresse)
                }
                .show()
        }

        DodoAccessibilityService.actif.observe(this) { majService(it) }

        montrer(accueil = Preferences.configFaite(this) && savedInstanceState?.getBoolean(SUR_BIENVENUE) != true)
        if (savedInstanceState == null) recevoir(intent)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putInt(PAGE, page)
        outState.putBoolean(SUR_BIENVENUE, ecranBienvenue.visibility == View.VISIBLE)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        recevoir(intent)
    }

    override fun onResume() {
        super.onResume()
        // Le calibrage et le morceau choisi ont pu changer dans la bulle pendant qu'on était dans le jeu.
        majListes()
    }

    override fun onDestroy() {
        calcul.shutdownNow()
        super.onDestroy()
    }

    /**
     * Versions de test seulement : `adb shell am start … --es serveur http://10.0.2.2:8000 --es jeton … --es nom …`
     * pointe l'appli sur un serveur local et y ouvre une session sans passer par Discord.
     */
    private fun reglagesDeTest() {
        intent.getStringExtra("serveur")?.let { Preferences.prefs(this).edit().putString("serveur", it).apply() }
        intent.getStringExtra("jeton")?.let { jeton ->
            Compte.enregistrer(this, jeton, org.json.JSONObject().put("id", 1).put("username", intent.getStringExtra("nom") ?: "Test"))
        }
    }

    /** Un MIDI ouvert depuis un gestionnaire de fichiers (« Ouvrir avec DodoTopia »). */
    private fun recevoir(intent: Intent?) {
        val uri = intent?.takeIf { it.action == Intent.ACTION_VIEW }?.data ?: return
        importer(uri)
        majListes()
    }

    /**
     * Écran large (paysage, tablette : 700 dp et plus) : deux colonnes au lieu d'une longue pile.
     * Bienvenue : l'accroche et le bouton à gauche, les étapes à droite. Accueil : le titre et le compte
     * sur une ligne ; page Jouer : l'état et le clavier à gauche, les morceaux à droite.
     */
    private fun disposerEnLarge() {
        val dp = resources.displayMetrics.density
        fun part(poids: Float, hauteur: Int = ViewGroup.LayoutParams.WRAP_CONTENT) = LinearLayout.LayoutParams(0, hauteur, poids)
        fun deplacer(vue: View, vers: LinearLayout, marge: Int) {
            (vue.parent as ViewGroup).removeView(vue)
            vers.addView(vue, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = marge })
        }
        // Au-delà de 1060 dp, les colonnes ne s'élargissent plus : elles se centrent.
        val surplus = ((resources.configuration.screenWidthDp - 1060) / 2).coerceAtLeast(0) * dp

        val gauche = findViewById<LinearLayout>(R.id.bienvenueGauche)
        findViewById<LinearLayout>(R.id.bienvenueColonnes).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(paddingLeft + surplus.toInt(), paddingTop, paddingRight + surplus.toInt(), paddingBottom)
        }
        deplacer(findViewById(R.id.blocContinuer), gauche, (20 * dp).toInt())
        findViewById<View>(R.id.bienvenueEspace).visibility = View.GONE
        gauche.layoutParams = part(2f, ViewGroup.LayoutParams.MATCH_PARENT)
        findViewById<View>(R.id.blocEtapes).layoutParams = part(3f).apply { marginStart = (24 * dp).toInt() }

        findViewById<LinearLayout>(R.id.entete).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(paddingLeft + surplus.toInt(), paddingTop, paddingRight + surplus.toInt(), paddingBottom)
        }
        findViewById<View>(R.id.enteteTitre).layoutParams = part(1f)
        findViewById<View>(R.id.bandeauCompte).layoutParams = part(1f).apply { marginStart = (20 * dp).toInt() }

        findViewById<LinearLayout>(R.id.jouerColonnes).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(paddingLeft + surplus.toInt(), paddingTop, paddingRight + surplus.toInt(), paddingBottom)
        }
        val etat = findViewById<LinearLayout>(R.id.colonneEtat)
        deplacer(findViewById(R.id.blocClavier), etat, (20 * dp).toInt())
        etat.layoutParams = part(1f)
        findViewById<View>(R.id.blocMorceaux).layoutParams = part(1f).apply {
            marginStart = (20 * dp).toInt()
            topMargin = (10 * dp).toInt()
        }
    }

    /** Entrée d'un écran ou d'une page : un fondu qui monte de quelques points. */
    private fun apparaitre(vue: View) {
        vue.alpha = 0f
        vue.translationY = 14 * resources.displayMetrics.density
        vue.animate().alpha(1f).translationY(0f).setDuration(200).start()
    }

    private fun montrer(accueil: Boolean) {
        val entrant = if (accueil) ecranAccueil else ecranBienvenue
        if (entrant.visibility != View.VISIBLE) apparaitre(entrant)
        ecranAccueil.visibility = if (accueil) View.VISIBLE else View.GONE
        ecranBienvenue.visibility = if (accueil) View.GONE else View.VISIBLE
        retour.isEnabled = !accueil && Preferences.configFaite(this)
    }

    private fun pilule(id: Int, texte: Int, ok: Boolean) = findViewById<TextView>(id).apply {
        setText(texte)
        setBackgroundResource(if (ok) R.drawable.pilule_ok else R.drawable.pilule_attente)
        setTextColor(getColor(if (ok) R.color.c_ok else R.color.c_ambre_texte))
    }

    /** Reflète l'état du service sur les deux écrans (« À activer » puis « Activé »). */
    private fun majService(actif: Boolean) {
        pilule(R.id.pilService, if (actif) R.string.pil_active else R.string.pil_a_activer, actif)
        pilule(R.id.pilServiceAccueil, if (actif) R.string.pil_active else R.string.pil_a_activer, actif)
        findViewById<TextView>(R.id.txtService).setText(if (actif) R.string.service_actif else R.string.service_inactif)
        findViewById<View>(R.id.carteService).setBackgroundResource(if (actif) R.drawable.carte else R.drawable.carte_attente)
        findViewById<View>(R.id.btnAcces).visibility = if (actif) View.GONE else View.VISIBLE
        findViewById<View>(R.id.lienRestreint).visibility = if (actif) View.GONE else View.VISIBLE
        // La ligne ne mène quelque part que tant que le service reste à activer.
        findViewById<View>(R.id.ligneService).isClickable = !actif

        findViewById<TextView>(R.id.btnContinuer).apply {
            setText(if (actif) R.string.continuer_pret else R.string.continuer_sans)
            setBackgroundResource(if (actif) R.drawable.btn_teal else R.drawable.btn_creme)
            setTextColor(getColor(if (actif) R.color.blanc else R.color.c_text_2))
        }
        findViewById<View>(R.id.txtContinuer).visibility = if (actif) View.INVISIBLE else View.VISIBLE
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

    // ------------------------------------------------------------------ morceaux et clavier

    private fun majListes() {
        val d = Preferences.disposition(this)
        val calibre = Preferences.calibre(this, d)
        pilule(R.id.pilTouches, if (calibre) R.string.pil_calibre else R.string.pil_a_calibrer, calibre)
        findViewById<TextView>(R.id.txtTouches).text =
            if (calibre) getString(R.string.touches_calibrees, getString(d.nom)) else getString(R.string.touches_a_calibrer)

        val claviers = findViewById<ViewGroup>(R.id.listeDispositions)
        claviers.removeAllViews()
        for (c in Dispositions.toutes) {
            val ligne = layoutInflater.inflate(R.layout.item_disposition, claviers, false)
            ligne.isSelected = c.id == d.id
            ligne.findViewById<MiniClavierView>(R.id.schema).montrer(c)
            ligne.findViewById<TextView>(R.id.titre).setText(c.nom)
            ligne.findViewById<TextView>(R.id.detail).setText(c.detail)
            ligne.findViewById<View>(R.id.etat).visibility = if (Preferences.calibre(this, c)) View.VISIBLE else View.GONE
            ligne.setOnClickListener {
                if (c.id != d.id) it.tic()
                Preferences.definirDisposition(this, c)
                majListes()
            }
            claviers.addView(ligne)
        }

        val choisi = biblio.choisi()
        val liste = findViewById<ViewGroup>(R.id.listeMorceaux)
        liste.removeAllViews()
        for (m in biblio.liste()) {
            val ligne = layoutInflater.inflate(R.layout.item_morceau, liste, false)
            ligne.isSelected = m.id == choisi.id
            ligne.findViewById<TextView>(R.id.titre).text = m.titre
            val meta = ligne.findViewById<TextView>(R.id.meta)
            meta.text = meta(m, couvertures["${m.id}|${d.id}"])
            if (couvertures["${m.id}|${d.id}"] == null) calculerCouverture(m, d, meta)
            ligne.setOnClickListener {
                if (m.id != choisi.id) it.tic()
                biblio.choisir(m.id)
                majListes()
            }
            if (!m.demo) {
                ligne.setOnLongClickListener {
                    DialoguePistes.ouvrir(this, biblio, m) {
                        // La couverture affichée dépend des pistes gardées.
                        couvertures.keys.removeAll { it.startsWith(m.id + "|") }
                        majListes()
                    }
                    true
                }
            }
            ligne.findViewById<View>(R.id.supprimer).apply {
                visibility = if (m.demo) View.GONE else View.VISIBLE
                contentDescription = getString(R.string.supprimer_morceau, m.titre)
                setOnClickListener { confirmerSuppression(m) }
            }
            liste.addView(ligne)
        }
    }

    /** La corbeille est à un doigt de la ligne qu'on choisit : on demande avant d'effacer le fichier. */
    private fun confirmerSuppression(m: Morceau) {
        MaterialAlertDialogBuilder(this)
            .setMessage(getString(R.string.supprimer_question, m.titre))
            .setNegativeButton(R.string.annuler, null)
            .setPositiveButton(R.string.supprimer) { _, _ ->
                biblio.supprimer(m.id)
                Annonce.montrer(this, getString(R.string.morceau_supprime, m.titre))
                majListes()
            }
            .show()
    }

    private fun meta(m: Morceau, couverture: Int?): String {
        val base = if (couverture == null) {
            getString(R.string.morceau_meta, minutes(m.dureeMs), m.nbNotes)
        } else {
            getString(R.string.morceau_meta_compat, minutes(m.dureeMs), m.nbNotes, couverture)
        }
        return if (m.demo) getString(R.string.morceau_exemple, base) else base
    }

    private fun calculerCouverture(m: Morceau, d: Disposition, cible: TextView) {
        calcul.execute {
            val couverture = try {
                Arrangeur.arranger(biblio.notes(m.id), d).couverture
            } catch (e: IOException) {
                return@execute
            } catch (e: MidiIllisible) {
                return@execute
            }
            runOnUiThread {
                couvertures["${m.id}|${d.id}"] = couverture
                // La ligne a pu être remplacée entre-temps : dans ce cas la prochaine liste lira le cache.
                if (cible.isAttachedToWindow) cible.text = meta(m, couverture)
            }
        }
    }

    private fun importer(uri: Uri) {
        try {
            val morceau = biblio.importer(uri)
            Annonce.montrer(this, getString(R.string.import_ok, morceau.titre))
        } catch (e: MidiIllisible) {
            SpikeLog.log("Import refusé : ${e.message} ($uri)")
            Annonce.montrer(this, getString(R.string.import_refuse, uri.lastPathSegment?.substringAfterLast('/') ?: ""), erreur = true)
        } catch (e: IOException) {
            Annonce.montrer(this, R.string.import_erreur, erreur = true)
        } catch (e: SecurityException) {
            Annonce.montrer(this, R.string.import_erreur, erreur = true)
        }
    }

    private fun ouvrirJeu() {
        val jeu = PAQUETS_JEU.firstNotNullOfOrNull { packageManager.getLaunchIntentForPackage(it) }
        if (jeu == null) {
            Annonce.montrer(this, R.string.jeu_absent, erreur = true)
        } else {
            startActivity(jeu)
        }
    }

    /** Onglet du bas ouvert (identifiant du bouton), pour le retrouver après une rotation. */
    private var page = 0

    companion object {
        /** Heartopia sur le Play Store (version globale). Déclaré dans <queries> du manifeste. */
        private val PAQUETS_JEU = listOf("com.xd.xdtglobal.gp")
        private const val PAGE = "page"
        private const val SUR_BIENVENUE = "sur_bienvenue"
    }
}
