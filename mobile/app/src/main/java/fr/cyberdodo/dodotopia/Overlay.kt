package fr.cyberdodo.dodotopia

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.PixelFormat
import android.graphics.PointF
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.ContextThemeWrapper
import android.view.Gravity
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.ImageView
import android.widget.ProgressBar
import android.widget.TextView
import java.util.Locale
import kotlin.math.hypot
import kotlin.math.min

/**
 * Tout ce que DodoTopia affiche par-dessus le jeu à l'étape 1, dans le style des ébauches
 * « DodoTopia Mobile » : la bulle, son menu, la carte de mesure en cours, le viseur et sa barre.
 * Ce sont des fenêtres TYPE_ACCESSIBILITY_OVERLAY, que seul le WindowManager du service
 * d'accessibilité a le droit de créer.
 *
 * À savoir pour les mesures : un geste envoyé par le service atterrit sur la fenêtre qui se trouve
 * à cet endroit, les nôtres comprises. D'où le menu replié pendant le métronome, la carte de mesure
 * non tactile et l'avertissement quand la bulle recouvre un repère.
 */
class Overlay(private val service: DodoAccessibilityService) {

    private enum class Etat { FERME, OUVERT, MESURE }
    private enum class Onglet { METRONOME, REPERES, CAPTURE }

    private val contexte: Context = ContextThemeWrapper(service, R.style.Theme_DodoOverlay)
    private val fenetres = service.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val gonfleur = LayoutInflater.from(contexte)
    private val prefs = service.getSharedPreferences(Preferences.FICHIER, Context.MODE_PRIVATE)
    private val principal = Handler(Looper.getMainLooper())
    private val dp = service.resources.displayMetrics.density

    private val reperes = mutableListOf<PointF>()
    private var onglet = Onglet.METRONOME
    private var resumeMetronome = ""
    private var resumeCapture = ""

    private var bulle: View? = null
    private var bulleParams: WindowManager.LayoutParams? = null
    private var aide: View? = null
    private var panneau: View? = null
    private var carte: View? = null
    private var viseur: View? = null
    private var barre: View? = null
    private var calque: ReperesView? = null

    init {
        chargerReperes()
    }

    private fun px(valeurDp: Int): Int = (valeurDp * dp).toInt()

    // ------------------------------------------------------------------ fenêtres

    private fun params(largeur: Int, hauteur: Int, drapeaux: Int = 0): WindowManager.LayoutParams =
        WindowManager.LayoutParams(
            largeur, hauteur,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            // NO_LIMITS + IN_SCREEN : x et y comptent depuis le coin de l'écran, et le viseur
            // peut dépasser du bord pour viser une touche collée au bord.
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or drapeaux,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
        }

    private fun retirer(vue: View?) {
        if (vue == null) return
        try {
            fenetres.removeView(vue)
        } catch (e: IllegalArgumentException) {
            // Déjà retirée (service coupé pendant une animation) : rien à faire.
        }
    }

    /**
     * Place une fenêtre à côté de la bulle, comme dans les ébauches : du côté libre, à 16 dp du cercle.
     * Si la largeur manque (téléphone en portrait), elle passe sous la bulle, ou au-dessus.
     */
    private fun placerPresDeLaBulle(p: WindowManager.LayoutParams, hautPrefere: Int?) {
        val b = bulleParams ?: return
        val ecran = tailleEcran(service)
        val marge = px(8)
        val aDroite = b.x + b.width / 2 > ecran.x / 2
        // La fenêtre de la bulle garde 10 dp de marge autour du cercle : 16 dp d'écart visible = 6 dp entre fenêtres.
        val x = if (aDroite) b.x - px(6) - p.width else b.x + b.width + px(6)
        if (x >= marge && x + p.width <= ecran.x - marge) {
            p.x = x
            p.y = (hautPrefere ?: (b.y + b.height / 2 - p.height / 2))
                .coerceIn(marge, (ecran.y - p.height - marge).coerceAtLeast(marge))
        } else {
            p.x = (ecran.x - p.width) / 2
            val dessous = b.y + b.height
            p.y = when {
                hautPrefere != null -> hautPrefere + px(24)
                dessous + p.height <= ecran.y - marge -> dessous
                b.y - p.height >= marge -> b.y - p.height
                else -> (ecran.y - p.height) / 2
            }
        }
    }

    /** Déplace une fenêtre au doigt. Sans glissement, c'est un clic. */
    private inner class Glisser(
        private val p: WindowManager.LayoutParams,
        private val seuil: Int,
        private val surClic: (() -> Unit)?,
        private val surLacher: (() -> Unit)?,
    ) : View.OnTouchListener {
        private var x0 = 0f
        private var y0 = 0f
        private var px = 0
        private var py = 0
        private var glisse = false

        @SuppressLint("ClickableViewAccessibility")
        override fun onTouch(v: View, ev: MotionEvent): Boolean {
            when (ev.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    x0 = ev.rawX; y0 = ev.rawY; px = p.x; py = p.y; glisse = false
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = ev.rawX - x0
                    val dy = ev.rawY - y0
                    if (!glisse && hypot(dx, dy) > seuil) glisse = true
                    if (glisse && v.isAttachedToWindow) {
                        p.x = px + dx.toInt(); p.y = py + dy.toInt()
                        fenetres.updateViewLayout(v, p)
                    }
                }
                MotionEvent.ACTION_UP -> if (glisse) surLacher?.invoke() else surClic?.invoke()
                MotionEvent.ACTION_CANCEL -> if (glisse) surLacher?.invoke()
            }
            return true
        }
    }

    /** Retire tout, bulle comprise : service coupé, ou bulle éteinte depuis l'appli. */
    fun fermerTout() {
        if (service.metronome.enCours) service.metronome.arreter { }
        principal.removeCallbacksAndMessages(null)
        fermerViseur()
        fermerPanneau()
        fermerCarte()
        fermerAide()
        retirer(bulle)
        bulle = null
        bulleParams = null
    }

    /** Les positions n'ont plus de sens après une rotation : on replie tout et on range la bulle. */
    fun surRotation() {
        if (bulle == null) return
        fermerViseur()
        fermerPanneau()
        fermerAide()
        // Les repères de l'autre orientation tomberaient à côté, voire hors écran.
        reperes.clear()
        chargerReperes()
        if (!service.metronome.enCours) etatBulle(Etat.FERME)
        principal.post { rangerBulle(anime = false) }
    }

    // ------------------------------------------------------------------ bulle

    fun montrerBulle() {
        if (bulle != null) return
        val vue = gonfleur.inflate(R.layout.overlay_bulle, null)
        val taille = px(TAILLE_BULLE_DP)
        val ecran = tailleEcran(service)
        val p = params(taille, taille).apply { x = ecran.x - taille; y = ecran.y * 2 / 5 - taille / 2 }
        vue.setOnTouchListener(
            Glisser(p, ViewConfiguration.get(contexte).scaledTouchSlop, ::clicBulle) { rangerBulle(anime = true) }
        )
        fenetres.addView(vue, p)
        bulle = vue
        bulleParams = p
        etatBulle(Etat.FERME)
        montrerAide()
    }

    private fun clicBulle() {
        fermerAide()
        when {
            service.metronome.enCours -> arreterMesure()
            viseur != null -> {
                fermerViseur()
                ouvrirPanneau()
            }
            panneau != null -> {
                fermerPanneau()
                etatBulle(Etat.FERME)
            }
            else -> ouvrirPanneau()
        }
    }

    /** Colle la bulle au bord gauche ou droit le plus proche, sans la laisser sortir en hauteur. */
    private fun rangerBulle(anime: Boolean) {
        val vue = bulle ?: return
        val p = bulleParams ?: return
        fermerAide()
        val ecran = tailleEcran(service)
        val taille = p.width
        val cible = if (p.x + taille / 2 < ecran.x / 2) 0 else ecran.x - taille
        p.y = p.y.coerceIn(0, ecran.y - taille)
        // Le menu suit la bulle : on le repose à côté de sa nouvelle place.
        val replacer = { if (panneau != null) reouvrirPanneau() }
        if (!anime) {
            p.x = cible
            if (vue.isAttachedToWindow) fenetres.updateViewLayout(vue, p)
            replacer()
            return
        }
        ValueAnimator.ofInt(p.x, cible).apply {
            duration = 180
            addUpdateListener {
                p.x = it.animatedValue as Int
                if (vue.isAttachedToWindow) fenetres.updateViewLayout(vue, p)
            }
            addListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) = replacer()
            })
            start()
        }
    }

    /** Les trois visages de la bulle des ébauches : fermée (pastille verte), ouverte (croix), en mesure (anneau ambre). */
    private fun etatBulle(etat: Etat) {
        val vue = bulle ?: return
        val badge = vue.findViewById<ImageView>(R.id.badge)
        vue.findViewById<View>(R.id.cercle).setBackgroundResource(
            if (etat == Etat.MESURE) R.drawable.bulle_fond_actif else R.drawable.bulle_fond
        )
        vue.findViewById<View>(R.id.imgBulle).alpha = if (etat == Etat.FERME) 1f else 0.4f
        vue.findViewById<View>(R.id.pastille).visibility = if (etat == Etat.FERME) View.VISIBLE else View.GONE
        vue.findViewById<View>(R.id.anneau).visibility = if (etat == Etat.MESURE) View.VISIBLE else View.GONE
        badge.visibility = if (etat == Etat.FERME) View.GONE else View.VISIBLE
        if (etat == Etat.MESURE) {
            // Dans les ébauches c'est un bouton pause ; ici l'appui arrête la mesure, d'où le carré.
            badge.setBackgroundResource(R.drawable.rond_ambre)
            badge.setImageResource(R.drawable.ic_stop)
            badge.imageTintList = ColorStateList.valueOf(contexte.getColor(R.color.blanc))
        } else {
            badge.setBackgroundResource(R.drawable.rond_sombre)
            badge.setImageResource(R.drawable.ic_fermer)
            badge.imageTintList = ColorStateList.valueOf(contexte.getColor(R.color.c_caramel_ink))
        }
    }

    /** « Appuie pour ouvrir DodoTopia » : quelques secondes à l'apparition de la bulle, sans gêner le jeu. */
    private fun montrerAide() {
        val b = bulleParams ?: return
        val vue = gonfleur.inflate(R.layout.overlay_aide, null)
        vue.measure(View.MeasureSpec.UNSPECIFIED, View.MeasureSpec.UNSPECIFIED)
        val p = params(vue.measuredWidth, vue.measuredHeight, WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE).apply {
            x = if (b.x > 0) b.x - vue.measuredWidth else b.x + b.width
            y = b.y + (b.height - vue.measuredHeight) / 2
        }
        fenetres.addView(vue, p)
        aide = vue
        principal.postDelayed(::fermerAide, 4500)
    }

    private fun fermerAide() {
        retirer(aide)
        aide = null
    }

    // ------------------------------------------------------------------ menu

    private fun ouvrirPanneau() {
        if (panneau != null || bulle == null) return
        val vue = gonfleur.inflate(R.layout.overlay_panneau, null)

        onglet(vue, R.id.ongletMetronome, R.drawable.ic_note, Onglet.METRONOME)
        onglet(vue, R.id.ongletReperes, R.drawable.ic_cible, Onglet.REPERES)
        onglet(vue, R.id.ongletCapture, R.drawable.ic_ecran, Onglet.CAPTURE)
        vue.findViewById<View>(R.id.pageMetronome).visibility = visible(onglet == Onglet.METRONOME)
        vue.findViewById<View>(R.id.pageReperes).visibility = visible(onglet == Onglet.REPERES)
        vue.findViewById<View>(R.id.pageCapture).visibility = visible(onglet == Onglet.CAPTURE)
        remplirEntete(vue)

        pas(vue, R.id.tempoMoins, R.id.tempoValeur, R.id.tempoPlus, "bpm", 120, 60, 240, 10) { "$it" }
        pas(vue, R.id.appuisMoins, R.id.appuisValeur, R.id.appuisPlus, "appuis", 16, 4, 64, 4) { "$it" }
        pas(vue, R.id.dureeMoins, R.id.dureeValeur, R.id.dureePlus, "duree_ms", 40, 20, 200, 10) { "$it ms" }
        vue.findViewById<TextView>(R.id.chipAccord).apply {
            isSelected = prefs.getBoolean("accord", false)
            setOnClickListener {
                isSelected = !isSelected
                prefs.edit().putBoolean("accord", isSelected).apply()
                remplirEntete(vue)
            }
        }
        vue.findViewById<View>(R.id.btnLancer).setOnClickListener { lancerMesure() }
        vue.findViewById<View>(R.id.btnPlacer).setOnClickListener { ouvrirViseur() }
        vue.findViewById<View>(R.id.btnEffacerReperes).setOnClickListener {
            reperes.clear()
            sauverReperes()
            remplirEntete(vue)
        }
        vue.findViewById<View>(R.id.btnCaptureService).setOnClickListener { capturer() }
        vue.findViewById<View>(R.id.lienOuvrir).setOnClickListener {
            fermerPanneau()
            etatBulle(Etat.FERME)
            service.startActivity(
                Intent(service, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        }

        val resume = when (onglet) {
            Onglet.METRONOME -> resumeMetronome
            Onglet.CAPTURE -> resumeCapture
            Onglet.REPERES -> ""
        }
        vue.findViewById<TextView>(R.id.txtResume).apply {
            text = resume
            visibility = visible(resume.isNotEmpty())
        }

        // Largeur des ébauches (330 dp), hauteur du contenu plafonnée à l'écran : au-delà, le menu défile.
        val ecran = tailleEcran(service)
        val largeur = min(px(LARGEUR_MENU_DP), ecran.x - px(16))
        vue.measure(
            View.MeasureSpec.makeMeasureSpec(largeur, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(ecran.y - px(16), View.MeasureSpec.AT_MOST)
        )
        val p = params(largeur, vue.measuredHeight)
        placerPresDeLaBulle(p, null)
        fenetres.addView(vue, p)
        panneau = vue
        etatBulle(Etat.OUVERT)
    }

    private fun fermerPanneau() {
        retirer(panneau)
        panneau = null
    }

    /** Le menu a une hauteur figée à l'ouverture : on le rouvre quand son contenu ou la place de la bulle change. */
    private fun reouvrirPanneau() {
        fermerPanneau()
        ouvrirPanneau()
    }

    private fun visible(oui: Boolean) = if (oui) View.VISIBLE else View.GONE

    private fun onglet(vue: View, id: Int, icone: Int, cible: Onglet) {
        vue.findViewById<TextView>(id).apply {
            isSelected = onglet == cible
            // Icône de 15 dp à gauche du libellé, de la couleur du texte, comme dans les ébauches.
            val dessin = contexte.getDrawable(icone)!!.mutate()
            dessin.setBounds(0, 0, px(15), px(15))
            dessin.setTint(currentTextColor)
            setCompoundDrawables(dessin, null, null, null)
            compoundDrawablePadding = px(5)
            val largeurTexte = paint.measureText(text.toString()).toInt() + px(20)
            // Centre le couple icône + texte dans la pilule (un TextView colle sinon l'icône au bord).
            post { setPadding(((width - largeurTexte) / 2).coerceAtLeast(px(6)), 0, px(6), 0) }
            gravity = Gravity.CENTER_VERTICAL
            setOnClickListener {
                if (onglet != cible) {
                    onglet = cible
                    reouvrirPanneau()
                }
            }
        }
    }

    /** Pastille, rôle, titre et compteur : la ligne d'en-tête du menu, à la couleur de l'onglet. */
    private fun remplirEntete(vue: View) {
        val icone = vue.findViewById<ImageView>(R.id.enteteIcone)
        val role = vue.findViewById<TextView>(R.id.enteteRole)
        val titre = vue.findViewById<TextView>(R.id.enteteTitre)
        val compte = vue.findViewById<TextView>(R.id.enteteCompte)
        val n = reperes.size
        val nReperes = when (n) {
            0 -> "aucun repère"
            1 -> "1 repère"
            else -> "$n repères"
        }
        when (onglet) {
            Onglet.METRONOME -> {
                icone.setBackgroundResource(R.drawable.rond_ambre)
                icone.setImageResource(R.drawable.ic_note)
                role.setTextColor(contexte.getColor(R.color.c_ambre_texte))
                role.text = "Test · $nReperes · " + if (prefs.getBoolean("accord", false)) "en accord" else "à tour de rôle"
                titre.text = "Métronome"
                compte.setBackgroundResource(R.drawable.pilule_ambre)
                compte.text = "${prefs.getInt("bpm", 120)} bpm"
            }
            Onglet.REPERES -> {
                val ecran = tailleEcran(service)
                icone.setBackgroundResource(R.drawable.rond_rose)
                icone.setImageResource(R.drawable.ic_cible)
                role.setTextColor(contexte.getColor(R.color.c_rose_encre))
                role.text = "Touches de l'instrument · écran ${ecran.x}×${ecran.y}"
                titre.text = if (n == 0) "Aucun repère placé" else if (n == 1) "1 repère placé" else "$n repères placés"
                compte.setBackgroundResource(R.drawable.pilule_rose)
                compte.text = "$n"
            }
            Onglet.CAPTURE -> {
                icone.setBackgroundResource(R.drawable.rond_menthe)
                icone.setImageResource(R.drawable.ic_ecran)
                role.setTextColor(contexte.getColor(R.color.c_menthe_encre))
                role.text = "Secours · service d'accessibilité"
                titre.text = "Capture d'écran"
                compte.setBackgroundResource(R.drawable.pilule_menthe)
                compte.text = "3 / s max"
            }
        }
    }

    /** Lie un réglage « − valeur + » (la ligne Vitesse des ébauches) à sa préférence. */
    private fun pas(
        vue: View, idMoins: Int, idValeur: Int, idPlus: Int,
        cle: String, defaut: Int, mini: Int, maxi: Int, saut: Int, libelle: (Int) -> String,
    ) {
        val valeur = vue.findViewById<TextView>(idValeur)
        valeur.text = libelle(prefs.getInt(cle, defaut))
        fun changer(sens: Int) {
            val v = (prefs.getInt(cle, defaut) + sens * saut).coerceIn(mini, maxi)
            prefs.edit().putInt(cle, v).apply()
            valeur.text = libelle(v)
            remplirEntete(vue)
        }
        vue.findViewById<View>(idMoins).setOnClickListener { changer(-1) }
        vue.findViewById<View>(idPlus).setOnClickListener { changer(1) }
    }

    // ------------------------------------------------------------------ métronome et capture

    private fun lancerMesure() {
        if (reperes.isEmpty()) {
            resumeMetronome = "Place d'abord un repère sur une touche de l'instrument (onglet Repères)."
            reouvrirPanneau()
            return
        }
        val bpm = prefs.getInt("bpm", 120)
        val intervalle = 60000L / bpm
        // Un geste envoyé pendant qu'un autre est en cours annule le premier :
        // l'appui doit finir avant le suivant, avec un peu de marge.
        val duree = min(prefs.getInt("duree_ms", 40).toLong(), intervalle - 20)
        val reglages = Reglages(
            bpm = bpm,
            appuis = prefs.getInt("appuis", 16),
            accord = prefs.getBoolean("accord", false),
            dureeMs = duree,
            reperes = reperes.map { PointF(it.x, it.y) },
        )
        val ecran = tailleEcran(service)
        SpikeLog.log(
            "Départ métronome · écran ${ecran.x}×${ecran.y} · repères " +
                reperes.joinToString(" ") { "(${it.x.toInt()},${it.y.toInt()})" } + alerteBulle()
        )
        fermerPanneau()
        etatBulle(Etat.MESURE)
        ouvrirCarte(reglages)
        service.metronome.lancer(reglages, { envoyes -> majCarte(reglages, envoyes) }, ::finMesure)
    }

    fun arreterMesure() {
        service.metronome.arreter(::finMesure)
    }

    private fun finMesure(texte: String) {
        if (bulle == null) return
        fermerCarte()
        Resultats.metronome.value = texte
        resumeMetronome = texte + alerteBulle()
        onglet = Onglet.METRONOME
        reouvrirPanneau()
    }

    /** La bulle avale les appuis qui tombent dessus : on le signale plutôt que de fausser la mesure en silence. */
    private fun alerteBulle(): String {
        val p = bulleParams ?: return ""
        val dessous = reperes.indexOfFirst {
            it.x >= p.x && it.x <= p.x + p.width && it.y >= p.y && it.y <= p.y + p.height
        }
        return if (dessous < 0) "" else "\nAttention : la bulle recouvre le repère ${dessous + 1}, déplace-la."
    }

    /** Carte « en lecture » des ébauches. Non tactile, pour ne pas avaler les appuis envoyés au jeu. */
    private fun ouvrirCarte(r: Reglages) {
        val vue = gonfleur.inflate(R.layout.overlay_carte, null)
        val n = r.reperes.size
        vue.findViewById<TextView>(R.id.carteRole).text =
            "Métronome · ${r.bpm} bpm · " + if (n == 1) "1 repère" else "$n repères"
        vue.findViewById<TextView>(R.id.carteTitre).text = "Mesure en cours"
        vue.findViewById<ProgressBar>(R.id.carteBarre).max = r.appuis
        vue.findViewById<TextView>(R.id.carteMeta).text =
            "Appui de ${r.dureeMs} ms · " + (if (r.accord) "accord · " else "") + "volume bas pour arrêter"
        val ecran = tailleEcran(service)
        val largeur = min(px(LARGEUR_MENU_DP), ecran.x - px(16))
        vue.measure(
            View.MeasureSpec.makeMeasureSpec(largeur, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED)
        )
        val p = params(largeur, vue.measuredHeight, WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE)
        placerPresDeLaBulle(p, px(18))
        fenetres.addView(vue, p)
        carte = vue
        majCarte(r, 0)
    }

    private fun majCarte(r: Reglages, envoyes: Int) {
        val vue = carte ?: return
        vue.findViewById<TextView>(R.id.carteCompte).text = "$envoyes / ${r.appuis}"
        vue.findViewById<ProgressBar>(R.id.carteBarre).progress = envoyes
        val pas = 60.0 / r.bpm
        vue.findViewById<TextView>(R.id.carteTemps).text = temps(envoyes * pas) + " / " + temps(r.appuis * pas)
    }

    private fun temps(secondes: Double): String {
        val s = secondes.toInt()
        return String.format(Locale.ROOT, "%d:%02d", s / 60, s % 60)
    }

    private fun fermerCarte() {
        retirer(carte)
        carte = null
    }

    private fun capturer() {
        fermerPanneau()
        // Le temps que le menu disparaisse de l'écran, sinon c'est lui qu'on photographie.
        principal.postDelayed({
            service.capturer { texte ->
                if (bulle != null) {
                    resumeCapture = texte
                    onglet = Onglet.CAPTURE
                    reouvrirPanneau()
                }
            }
        }, 400)
    }

    // ------------------------------------------------------------------ viseur

    private fun ouvrirViseur() {
        fermerPanneau()
        if (viseur != null) return
        val ecran = tailleEcran(service)

        val fond = ReperesView(contexte, reperes)
        fenetres.addView(
            fond,
            params(
                WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
            )
        )
        calque = fond

        val cible = ViseurView(contexte)
        val taille = px(TAILLE_VISEUR_DP)
        val p = params(taille, taille).apply { x = (ecran.x - taille) / 2; y = (ecran.y - taille) / 2 }
        // Seuil nul : le viseur suit le doigt dès le premier pixel, pour viser fin.
        cible.setOnTouchListener(Glisser(p, 0, null, null))
        fenetres.addView(cible, p)
        viseur = cible

        val commandes = gonfleur.inflate(R.layout.overlay_barre_viseur, null)
        val compte = commandes.findViewById<TextView>(R.id.txtCompte)
        fun majCompte() {
            compte.text = "${reperes.size}"
            fond.invalidate()
        }
        commandes.findViewById<View>(R.id.btnValider).setOnClickListener {
            // Position réelle à l'écran, pas celle qu'on a demandée : c'est elle que dispatchGesture attend.
            val coin = IntArray(2)
            cible.getLocationOnScreen(coin)
            val point = PointF(coin[0] + cible.width / 2f, coin[1] + cible.height / 2f)
            reperes.add(point)
            sauverReperes()
            SpikeLog.log("Repère ${reperes.size} : (${point.x.toInt()}, ${point.y.toInt()})")
            majCompte()
        }
        commandes.findViewById<View>(R.id.btnRetirer).setOnClickListener {
            if (reperes.isNotEmpty()) {
                reperes.removeAt(reperes.size - 1)
                sauverReperes()
                majCompte()
            }
        }
        commandes.findViewById<View>(R.id.btnTerminer).setOnClickListener {
            fermerViseur()
            onglet = Onglet.REPERES
            ouvrirPanneau()
        }
        majCompte()
        // Largeur mesurée à la main : une fenêtre WRAP_CONTENT est d'abord bridée à 320 dp par Android,
        // ce qui tronquait le dernier bouton.
        commandes.measure(
            View.MeasureSpec.makeMeasureSpec(ecran.x - px(16), View.MeasureSpec.AT_MOST),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED)
        )
        // En haut au centre : les touches de l'instrument sont en bas de l'écran.
        val q = params(commandes.measuredWidth, WindowManager.LayoutParams.WRAP_CONTENT).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = px(12)
        }
        fenetres.addView(commandes, q)
        barre = commandes
    }

    private fun fermerViseur() {
        retirer(viseur); viseur = null
        retirer(barre); barre = null
        retirer(calque); calque = null
    }

    // ------------------------------------------------------------------ repères enregistrés

    private fun sauverReperes() {
        val ecran = tailleEcran(service)
        prefs.edit()
            .putString("reperes", reperes.joinToString(";") { "${it.x},${it.y}" })
            .putString("reperes_ecran", "${ecran.x}x${ecran.y}")
            .apply()
    }

    private fun chargerReperes() {
        // Des repères placés dans une autre orientation viseraient à côté : on repart de zéro.
        val ecran = tailleEcran(service)
        if (prefs.getString("reperes_ecran", null) != "${ecran.x}x${ecran.y}") return
        for (morceau in prefs.getString("reperes", "").orEmpty().split(';')) {
            val xy = morceau.split(',')
            val x = xy.getOrNull(0)?.toFloatOrNull() ?: continue
            val y = xy.getOrNull(1)?.toFloatOrNull() ?: continue
            reperes.add(PointF(x, y))
        }
    }

    companion object {
        /** Cercle de 66 dp plus 10 dp de marge de chaque côté (ombre, pastille, anneau). */
        private const val TAILLE_BULLE_DP = 86
        private const val LARGEUR_MENU_DP = 330
        private const val TAILLE_VISEUR_DP = 96
    }
}
