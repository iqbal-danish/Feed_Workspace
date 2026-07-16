"use strict";

var QWebChannelMessageTypes = {
    Init: 0,
    Idle: 1,
    NewMetaData: 2,
    PlayEffect: 3,
    QtSignal: 4,
    QtPropertyProposed: 5,
    QtPropertySet: 6,
    Signal: 7,
    PropertyUpdate: 8,
    InitResponse: 9
};

var QWebChannel = function(transport, initCallback) {
    if (typeof transport !== "object" || typeof transport.send !== "function") {
        console.error("The QWebChannel transport object is invalid!");
        return;
    }

    var channel = this;
    this.transport = transport;
    this.execCallbacks = {};
    this.execId = 0;
    this.objects = {};

    this.send = function(data) {
        if (typeof data !== "string") {
            data = JSON.stringify(data);
        }
        channel.transport.send(data);
    };

    this.transport.onmessage = function(message) {
        var mdata = message.data;
        if (typeof mdata === "string") {
            mdata = JSON.parse(mdata);
        }
        if (mdata.id !== undefined) {
            var callback = channel.execCallbacks[mdata.id];
            if (callback) {
                delete channel.execCallbacks[mdata.id];
                callback(mdata.data);
            }
            return;
        }
        switch (mdata.type) {
            case QWebChannelMessageTypes.QtSignal:
                channel.handleSignal(mdata);
                break;
            case QWebChannelMessageTypes.PropertyUpdate:
                channel.handlePropertyUpdate(mdata);
                break;
            case QWebChannelMessageTypes.InitResponse:
                channel.handleInitResponse(mdata, initCallback);
                break;
            default:
                console.error("Unknown message type: " + mdata.type);
                break;
        }
    };

    this.exec = function(action, callback) {
        if (channel.execId === undefined) {
            channel.execId = 0;
        }
        if (callback) {
            var id = channel.execId++;
            channel.execCallbacks[id] = callback;
            action.id = id;
        }
        channel.send(action);
    };

    this.handleInitResponse = function(data, initCallback) {
        for (var objectName in data.interfaces) {
            channel.objects[objectName] = new QObject(objectName, data.interfaces[objectName], channel);
        }
        for (var objectName in channel.objects) {
            channel.objects[objectName].__postInit__();
        }
        if (initCallback) {
            initCallback(channel);
        }
    };

    this.handleSignal = function(data) {
        var object = channel.objects[data.object];
        if (object) {
            object.handleSignal(data.signal, data.args);
        } else {
            console.warn("Unhandled signal: " + data.object + "::" + data.signal);
        }
    };

    this.handlePropertyUpdate = function(data) {
        for (var i = 0; i < data.signals.length; ++i) {
            var signal = data.signals[i];
            var object = channel.objects[signal.object];
            if (object) {
                object.handlePropertyUpdate(signal.properties, signal.signals);
            }
        }
    };

    channel.send({type: QWebChannelMessageTypes.Init});
};

function QObject(name, data, channel) {
    this.__id__ = name;
    this.__channel__ = channel;
    this.__properties__ = {};
    this.__signals__ = {};

    var object = this;

    for (var i = 0; i < data.methods.length; ++i) {
        var method = data.methods[i];
        this[method[0]] = (function(methodName) {
            return function() {
                var args = [];
                for (var j = 0; j < arguments.length; ++j) {
                    args.push(arguments[j]);
                }
                var callback;
                if (args.length > 0 && typeof args[args.length - 1] === "function") {
                    callback = args.pop();
                }
                object.__channel__.exec({
                    "type": QWebChannelMessageTypes.PlayEffect,
                    "object": object.__id__,
                    "method": methodName,
                    "args": args
                }, callback);
            };
        })(method[0]);
    }

    this.handleSignal = function(signalName, args) {
        var sig = object.__signals__[signalName];
        if (sig) {
            for (var i = 0; i < sig.connections.length; ++i) {
                sig.connections[i].apply(null, args);
            }
        }
    };

    this.handlePropertyUpdate = function(properties, signals) {
        for (var propName in properties) {
            object.__properties__[propName] = properties[propName];
            var signalName = signals[propName];
            var signal = object.__signals__[signalName];
            if (signal) {
                for (var i = 0; i < signal.connections.length; ++i) {
                    signal.connections[i](properties[propName]);
                }
            }
        }
    };
}

QObject.prototype.__postInit__ = function() {
    var object = this;
    for (var propName in this.__properties__) {
        (function(prop) {
            Object.defineProperty(object, prop, {
                get: function() {
                    return object.__properties__[prop];
                },
                set: function(value) {
                    console.warn("Property set from JS ignored. Set properties on Python side instead.");
                }
            });
        })(propName);
    }
};

function QWebChannelSignal(object, name, channel) {
    this.__object__ = object;
    this.__name__ = name;
    this.__channel__ = channel;
    this.connections = [];
}

QWebChannelSignal.prototype.connect = function(callback) {
    if (this.connections.indexOf(callback) === -1) {
        this.connections.push(callback);
    }
};

QWebChannelSignal.prototype.disconnect = function(callback) {
    var index = this.connections.indexOf(callback);
    if (index !== -1) {
        this.connections.splice(index, 1);
    }
};

if (typeof module === "object") {
    module.exports = {
        QWebChannel: QWebChannel
    };
}
