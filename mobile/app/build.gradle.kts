import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Clé de signature : mobile/keystore.properties (hors dépôt) donne storeFile, storePassword, keyAlias, keyPassword.
// Sans ce fichier, l'APK release part avec la clé debug : installable, mais pas distribuable
// (une mise à jour signée d'une autre clé est refusée par Android).
val cle = Properties().apply {
    val fichier = rootProject.file("keystore.properties")
    if (fichier.exists()) fichier.inputStream().use { load(it) }
}

android {
    namespace = "fr.cyberdodo.dodotopia"
    compileSdk = 35

    defaultConfig {
        applicationId = "fr.cyberdodo.dodotopia"
        minSdk = 26
        targetSdk = 35
        versionCode = 9
        versionName = "0.7.2"
    }

    signingConfigs {
        if (cle.containsKey("storeFile")) {
            create("release") {
                storeFile = file(cle.getProperty("storeFile"))
                storePassword = cle.getProperty("storePassword")
                keyAlias = cle.getProperty("keyAlias")
                keyPassword = cle.getProperty("keyPassword")
            }
        }
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.lifecycle:lifecycle-livedata-ktx:2.8.7")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
}
