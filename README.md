# izone_custom_component
iZone custom component for home assistant.

For the [iZone](http://izone.com.au/) air conditioning system available in West Australia.

I have noted some issues with connecting to the system if you hammer it with lots of commands in a short space of time. Sometimes it stops responding. I believe this is the system itself.

# Installation

Checkout the subdirectories into the custom_components subdir of the config directory of home assistant.

# Configuration

Just put 
```
izone:
```

in the HA config file and it should run. It will find the iZone system on the local network.
