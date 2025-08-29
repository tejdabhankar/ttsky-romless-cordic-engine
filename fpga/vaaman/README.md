## Implementation of Romless Cordic on Vaaman 

Vaaman is SBC from Vicarak.in it has Efinix Trion T120 FPGA along with Rockchip RK3399. [Crowd Supply](www.crowdsupply.com/vicharak/vaaman)




### What you need:
- All the wires should be of identical lengths. 
- You will need a dummy SPI device in your Linux kernel (e.g., `/dev/spidev1.0`, here 1 is bus and 0 is device).


Here are hte steps you can use for creatign the dummy SPI.

 ### Enable spidev on VAAMAN
 
 To enable `spidev` on your `Vaaman boards`, do as per the below instructions. **I will soon push it with the kernel updates.**
 
     * Resources: [rk3399-vaaman-spi2-dev.dtbo.disabled.gz](https://github.com/user-attachments/files/21556984/rk3399-vaaman-spi2-dev.dtbo.disabled.gz)
 
     * Prerequisite: gzip: `sudo apt install gzip`
 
 
     1. Use the following command on your Vaaman board  ** (Please add your GH access token)**
 
 
 ```
 wget --header="Authorization: token <YOUR_PERSONAL_ACCESS_TOKEN>" --header="Accept: application/octet-stream" https://github.com/user-attachments/files/21556984/rk3399-vaaman-spi2-dev.dtbo.disabled.gz -O rk3399-vaaman-spi2-dev.dtbo.disabled.gz
```

    2. Unzip it.


```
gzip -d rk3399-vaaman-spi2-dev.dtbo.disabled.gz
```

    3. Copy it to your overlays dir.


```
sudo cp rk3399-vaaman-spi2-dev.dtbo.disabled /boot/overlays-$(uname -r)
```

    4. Use `vicharak-config` to enable `[ ] Enable SPI 2 [dummy dev] Controller on 40-Pin GPIO`

    5. `sudo reboot`


#### Pin assignments:

| Pin    | CPU Pin | FPGA Pin |
|---------|-------------|---------------|
|`sclk`  |7              |H13 - 7    |
|`mosi`|29       |E9 - 29|
|`miso`|31|L15 - 31|
|`cs_n`|33|L18 - 33|
--------------------------------------------------------------------------------------------