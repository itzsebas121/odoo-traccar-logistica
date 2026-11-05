#!/bin/sh
set -e

echo "[Traccar Entrypoint] Generando configuracion para PostgreSQL..."

cat <<EOF > /opt/traccar/conf/traccar.xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE properties SYSTEM 'http://java.sun.com/dtd/properties.dtd'>
<properties>

    <!-- Base de datos PostgreSQL para Traccar Server -->
    <entry key='database.driver'>org.postgresql.Driver</entry>
    <entry key='database.url'>jdbc:postgresql://${TRACCAR_DB_HOST:-db}:${TRACCAR_DB_PORT:-5432}/${TRACCAR_DB_NAME:-traccar}</entry>
    <entry key='database.user'>${TRACCAR_DB_USER:-traccar}</entry>
    <entry key='database.password'>${TRACCAR_DB_PASSWORD}</entry>

    <!-- Configuracion de Web Console y API REST -->
    <entry key='web.port'>8082</entry>
    <entry key='web.path'>./web</entry>

    <!-- Receptor GPS para Traccar Client (Protocolo OsmAnd) -->
    <entry key='osmand.port'>5055</entry>

    <!-- Nivel de logging -->
    <entry key='logger.level'>info</entry>

</properties>
EOF

echo "[Traccar Entrypoint] Iniciando Traccar Server..."
exec /opt/traccar/jre/bin/java -XX:+ExitOnOutOfMemoryError -jar tracker-server.jar conf/traccar.xml

